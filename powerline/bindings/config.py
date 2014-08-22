# vim:fileencoding=utf-8:noet
from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import re
import sys

from powerline.config import POWERLINE_ROOT, TMUX_CONFIG_DIRECTORY
from powerline.lib.config import ConfigLoader
from powerline import generate_config_finder, load_config, create_logger, PowerlineLogger, finish_common_config, Powerline
from powerline.lib.shell import which
from powerline.bindings.tmux import TmuxVersionInfo, run_tmux_command, get_tmux_version
from powerline.lib.encoding import get_preferred_output_encoding
from powerline.renderers.tmux import attr_to_tmux_attr


CONFIG_FILE_NAME = re.compile(r'powerline_tmux_(?P<major>\d+)\.(?P<minor>\d+)(?P<suffix>[a-z]+)?(?:_(?P<mod>plus|minus))?\.conf')
CONFIG_MATCHERS = {
	None: (lambda a, b: a.major == b.major and a.minor == b.minor),
	'plus': (lambda a, b: a[:2] <= b[:2]),
	'minus': (lambda a, b: a[:2] >= b[:2]),
}
CONFIG_PRIORITY = {
	None: 3,
	'plus': 2,
	'minus': 1,
}


def list_all_tmux_configs():
	'''List all version-specific tmux configuration files'''
	directory = TMUX_CONFIG_DIRECTORY
	for root, dirs, files in os.walk(directory):
		dirs[:] = ()
		for fname in files:
			match = CONFIG_FILE_NAME.match(fname)
			if match:
				assert match.group('suffix') is None
				yield (
					os.path.join(root, fname),
					CONFIG_MATCHERS[match.group('mod')],
					CONFIG_PRIORITY[match.group('mod')],
					TmuxVersionInfo(
						int(match.group('major')),
						int(match.group('minor')),
						match.group('suffix'),
					),
				)


def get_tmux_configs(version):
	'''Get tmux configuration suffix given parsed tmux version

	:param TmuxVersionInfo version: Parsed tmux version.
	'''
	for fname, matcher, priority, file_version in list_all_tmux_configs():
		if matcher(file_version, version):
			yield (fname, priority + file_version.minor * 10 + file_version.major * 10000)


def source_tmux_files(pl, args):
	'''Source relevant version-specific tmux configuration files

	Files are sourced in the following order:
	* First relevant files with older versions are sourced.
	* If files for same versions are to be sourced then first _minus files are 
	  sourced, then _plus files and then files without _minus or _plus suffixes.
	'''
	version = get_tmux_version(pl)
	for fname, priority in sorted(get_tmux_configs(version), key=(lambda v: v[1])):
		run_tmux_command('source', fname)
	if not os.environ.get('POWERLINE_COMMAND'):
		cmd = deduce_command()
		if cmd:
			run_tmux_command('set-environment', '-g', 'POWERLINE_COMMAND', deduce_command())
	run_tmux_command('refresh-client')


def init_color_variables(pl, args):
	powerline = Powerline('tmux')
	# TODO Move configuration files loading out of Powerline object and use it 
	# directly
	powerline.update_renderer()
	# FIXME Use something more stable then `theme_kwargs`
	colorscheme = powerline.renderer_options['theme_kwargs']['colorscheme']

	def get_highlighting(group):
		return colorscheme.get_highlighting([group], None)

	for varname, highlight_group in (
		('_POWERLINE_BACKGROUND_COLOR', 'background'),
		('_POWERLINE_ACTIVE_WINDOW_STATUS_COLOR', 'active_window_status'),
		('_POWERLINE_WINDOW_STATUS_COLOR', 'window_status'),
		('_POWERLINE_ACTIVITY_STATUS_COLOR', 'activity_status'),
		('_POWERLINE_BELL_STATUS_COLOR', 'bell_status'),
		('_POWERLINE_WINDOW_COLOR', 'window'),
		('_POWERLINE_WINDOW_DIVIDER_COLOR', 'window:divider'),
		('_POWERLINE_WINDOW_CURRENT_COLOR', 'window:current'),
		('_POWERLINE_WINDOW_NAME_COLOR', 'window_name'),
		('_POWERLINE_SESSION_COLOR', 'session'),
	):
		highlight = get_highlighting(highlight_group)
		run_tmux_command('set-environment', '-g', varname, powerline.renderer.hlstyle(**highlight)[2:-1])
		run_tmux_command('set-environment', '-r', varname)
	for varname, prev_group, next_group in (
		('_POWERLINE_WINDOW_CURRENT_HARD_DIVIDER_COLOR', 'window', 'window:current'),
		('_POWERLINE_WINDOW_CURRENT_HARD_DIVIDER_NEXT_COLOR', 'window:current', 'window'),
		('_POWERLINE_SESSION_HARD_DIVIDER_NEXT_COLOR', 'session', 'background'),
	):
		prev_highlight = get_highlighting(prev_group)
		next_highlight = get_highlighting(next_group)
		run_tmux_command(
			'set-environment', '-g', varname,
			powerline.renderer.hlstyle(
				fg=prev_highlight['bg'],
				bg=next_highlight['bg'],
				attr=0,
			)[2:-1]
		)
		run_tmux_command('set-environment', '-r', varname)
	for varname, attr, group in (
		('_POWERLINE_ACTIVE_WINDOW_FG', 'fg', 'active_window_status'),
		('_POWERLINE_WINDOW_STATUS_FG', 'fg', 'window_status'),
		('_POWERLINE_ACTIVITY_STATUS_FG', 'fg', 'activity_status'),
		('_POWERLINE_ACTIVITY_STATUS_ATTR', 'attr', 'activity_status'),
		('_POWERLINE_BELL_STATUS_FG', 'fg', 'bell_status'),
		('_POWERLINE_BELL_STATUS_ATTR', 'attr', 'bell_status'),
		('_POWERLINE_BACKGROUND_FG', 'fg', 'background'),
		('_POWERLINE_BACKGROUND_BG', 'bg', 'background'),
		('_POWERLINE_SESSION_FG', 'fg', 'session'),
		('_POWERLINE_SESSION_BG', 'bg', 'session'),
		('_POWERLINE_SESSION_ATTR', 'attr', 'session'),
		('_POWERLINE_SESSION_PREFIX_FG', 'fg', 'session:prefix'),
		('_POWERLINE_SESSION_PREFIX_BG', 'bg', 'session:prefix'),
		('_POWERLINE_SESSION_PREFIX_ATTR', 'attr', 'session:prefix'),
	):
		if attr == 'attr':
			attrs = attr_to_tmux_attr(get_highlighting(group)[attr])
			run_tmux_command(
				'set-environment', '-g', varname,
				']#['.join(attrs)
			)
			run_tmux_command(
				'set-environment', '-g', varname + '_LEGACY',
				','.join(attrs)
			)
			run_tmux_command('set-environment', '-r', varname + '_LEGACY')
		else:
			run_tmux_command(
				'set-environment', '-g', varname,
				'colour' + str(get_highlighting(group)[attr][0])
			)
		run_tmux_command('set-environment', '-r', varname)


def get_main_config(args):
	find_config_files = generate_config_finder()
	config_loader = ConfigLoader(run_once=True)
	return load_config('config', find_config_files, config_loader)


def create_powerline_logger(args):
	config = get_main_config(args)
	common_config = finish_common_config(get_preferred_output_encoding(), config['common'])
	logger = create_logger(common_config)
	return PowerlineLogger(use_daemon_threads=True, logger=logger, ext='config')


def check_command(cmd):
	if which(cmd):
		return cmd


def deduce_command():
	'''Deduce which command to use for ``powerline``

	Candidates:

	* ``powerline``. Present only when installed system-wide.
	* ``{powerline_root}/scripts/powerline``. Present after ``pip install -e`` 
	  was run and C client was compiled (in this case ``pip`` does not install 
	  binary file).
	* ``{powerline_root}/client/powerline.sh``. Useful when ``sh``, ``sed`` and 
	  ``socat`` are present, but ``pip`` or ``setup.py`` was not run.
	* ``{powerline_root}/client/powerline.py``. Like above, but when one of 
	  ``sh``, ``sed`` and ``socat`` was not present.
	* ``powerline-render``. Should not really ever be used.
	* ``{powerline_root}/scripts/powerline-render``. Same.
	'''
	return (
		None
		or check_command('powerline')
		or check_command(os.path.join(POWERLINE_ROOT, 'scripts', 'powerline'))
		or ((which('sh') and which('sed') and which('socat'))
			and check_command(os.path.join(POWERLINE_ROOT, 'client', 'powerline.sh')))
		or check_command(os.path.join(POWERLINE_ROOT, 'client', 'powerline.py'))
		or check_command('powerline-render')
		or check_command(os.path.join(POWERLINE_ROOT, 'scripts', 'powerline-render'))
	)


def shell_command(pl, args):
	cmd = deduce_command()
	if cmd:
		print(cmd)
	else:
		sys.exit(1)


def uses(pl, args):
	component = args.component
	if not component:
		raise ValueError('Must specify component')
	shell = args.shell
	template = 'POWERLINE_NO_{shell}_{component}'
	for sh in (shell, 'shell') if shell else ('shell'):
		varname = template.format(shell=sh.upper(), component=component.upper())
		if os.environ.get(varname):
			sys.exit(1)
	config = get_main_config(args)
	if component in config.get('ext', {}).get('shell', {}).get('components', ('tmux', 'prompt')):
		sys.exit(0)
	else:
		sys.exit(1)
