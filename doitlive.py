#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
  doitlive
  ~~~~~~~~

  A tool for "live" presentations in the terminal.

  :copyright: (c) 2014 by Steven Loria.
  :license: MIT, see LICENSE for more details.
"""

from __future__ import unicode_literals
import datetime as dt
import functools
import os
import sys
import re
import getpass
import socket
import subprocess
from tempfile import NamedTemporaryFile
from collections import OrderedDict

import click
from click import echo, style, secho, getchar
from click.termui import strip_ansi

__version__ = '2.1.0-dev'
__author__ = 'Steven Loria'
__license__ = 'MIT'

env = os.environ
PY2 = int(sys.version[0]) == 2
if not PY2:
    unicode = str
    basestring = (str, bytes)
else:
    from codecs import open
    open = open

THEMES = OrderedDict([
    ('default', '{user.cyan.bold}@{hostname.blue}:{dir.green} $'),

    ('sorin', '{cwd.cyan} {git_branch.green.git} '
        '{r_angle.red}{r_angle.yellow}{r_angle.green}'),

    ('nicolauj', '{r_angle.white}'),

    ('steeef', '{user.red} at {hostname.yellow} in {cwd.green} '
                '{git_branch.cyan.paren}\n$'),

    ('redhat', '[{user}@{hostname} {dir}]$'),
    ('redhat_color', '[{user.red.bold}@{hostname.red} {dir.blue}]$'),

    ('walters', '{user}@{hostname.underlined}>'),
    ('walters_color', '{user.cyan.bold}@{hostname.blue.underlined}>'),

    ('minimal', '{dir} {git_branch.square} »'),
    ('minimal_color', '{dir.cyan} {git_branch.blue.square} »'),

    ('osx', '{hostname}:{dir} {user}$'),
    ('osx_color', '{hostname.blue}:{dir.green} {user.cyan}$'),

    ('pws', '+{now:%I:%M}%'),

    ('robbyrussell', '{r_arrow.red} {dir.cyan} {git_branch.red.paren.git}'),

])


ESC = '\x1b'
RETURNS = {'\r', '\n'}
OPTION_RE = re.compile(r'^#\s?doitlive\s+'
            '(?P<option>prompt|shell|alias|env|speed):'
            '\s*(?P<arg>.+)$')


TESTING = False


class Style(object):
    """Descriptor that adds ANSI styling when accessed."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __get__(self, instance, owner):
        return TermString(style(instance, **self.kwargs))


class TermString(unicode):
    """A string-like object that can be formatted with ANSI styles. Useful for
    styling strings within a string.format "template."
    """

    # Colors

    blue = Style(fg='blue')
    magenta = Style(fg='magenta')
    red = Style(fg='red')
    white = Style(fg='white')
    green = Style(fg='green')
    black = Style(fg='black')
    yellow = Style(fg='yellow')
    cyan = Style(fg='cyan')
    reset = Style(fg='reset')

    # Styling

    bold = Style(bold=True)
    blink = Style(blink=True)
    underlined = Style(underline=True)
    dim = Style(dim=True)

    def _bracketed(self, left, right):
        if strip_ansi(self):
            return TermString(''.join([left, self, right]))
        else:
            return TermString('\b')

    @property
    def paren(self):
        return self._bracketed('(', ')')

    @property
    def square(self):
        return self._bracketed('[', ']')

    @property
    def curly(self):
        return self._bracketed('{', '}')

    @property
    def git(self):
        if strip_ansi(self):
            return TermString('{}:{}'.format(style('git', fg='blue'), self))
        else:
            return TermString('\b')


def get_current_git_branch():
    command = ['git', 'symbolic-ref', '--short', '-q', 'HEAD']
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = proc.communicate()
        return out.strip()
    except subprocess.CalledProcessError:
        pass
    return ''


# Some common symbols used in prompts
R_ANGLE = TermString('❯')
R_ANGLE_DOUBLE = TermString('»')
R_ARROW = TermString('➔')
DOLLAR = TermString('$')
PERCENT = TermString('%')

def get_prompt_state():
    full_cwd = os.getcwd()
    cwd_raw = full_cwd.replace(env['HOME'], '~')
    dir_raw = '~' if full_cwd == env['HOME'] else os.path.split(full_cwd)[-1]
    return {
        'user': TermString(getpass.getuser()),
        'cwd': TermString(cwd_raw),
        'dir': TermString(dir_raw),
        'hostname': TermString(socket.gethostname()),
        'git_branch': TermString(get_current_git_branch()),
        # Symbols
        'r_angle': R_ANGLE,
        'r_angle_double': R_ANGLE_DOUBLE,
        'r_arrow': R_ARROW,
        'dollar': DOLLAR,
        'percent': PERCENT,
        'now': dt.datetime.now(),
    }


def ensure_utf(string):
    return string.encode('utf-8') if PY2 else string


def write_commands(fp, command, args):
    if args:
        for arg in args:
            line = '{command} {arg}\n'.format(**locals())
            fp.write(ensure_utf(line))
    return None


def write_directives(fp, directive, args):
    if args:
        for arg in args:
            line = '#doitlive {directive}: {arg}\n'.format(**locals())
            fp.write(ensure_utf(line))
    return None


def run_command(cmd, shell=None, aliases=None, envvars=None, test_mode=False):
    shell = shell or env.get('DOITLIVE_INTERPRETER') or '/bin/bash'
    if cmd.startswith("cd "):
        directory = cmd.split()[1]
        try:
            os.chdir(os.path.expanduser(directory))
        except OSError:
            echo('No such file or directory: {}'.format(directory))

    else:
        # Need to make a temporary command file so that $ENV are used correctly
        # and that shell built-ins, e.g. "source" work
        with NamedTemporaryFile('w') as fp:
            fp.write('#!{0}\n'.format(shell))
            fp.write('# -*- coding: utf-8 -*-\n')
            # Make aliases work in bash:
            if 'bash' in shell:
                fp.write("shopt -s expand_aliases\n")

            # Write envvars and aliases
            write_commands(fp, 'export', envvars)
            write_commands(fp, 'alias', aliases)

            cmd_line = cmd + '\n'
            fp.write(ensure_utf(cmd_line))
            fp.flush()
            if test_mode:
                output = subprocess.check_output([shell, fp.name])
                echo(output)
            else:
                return subprocess.call([shell, fp.name])

def wait_for(chars):
    while True:
        in_char = getchar()
        if in_char == ESC:
            echo()
            raise click.Abort()
        if in_char in chars:
            echo()
            return in_char

def magictype(text, shell, prompt_template='default', aliases=None,
        envvars=None, speed=1, test_mode=False):
    prompt_func = make_prompt_formatter(prompt_template)
    prompt = prompt_func()
    echo(prompt + ' ', nl=False)
    i = 0
    while i < len(text):
        char = text[i:i + speed]
        in_char = getchar()
        if in_char == ESC:
            echo()
            raise click.Abort()
        echo(char, nl=False)
        i += speed
    wait_for(RETURNS)
    run_command(text, shell, aliases=aliases, envvars=envvars,
        test_mode=test_mode)


def format_prompt(prompt):
    return prompt.format(**get_prompt_state())


def make_prompt_formatter(template):
    tpl = THEMES.get(template) or template
    return lambda: format_prompt(tpl)


def run(commands, shell='/bin/bash', prompt_template='default', speed=1,
        test_mode=False):
    secho("We'll do it live!", fg='red', bold=True)
    secho('STARTING SESSION: Press Ctrl-C at any time to exit.',
        fg='yellow', bold=True)

    click.pause()
    click.clear()
    aliases, envvars = [], []
    for line in commands:
        command = line.strip()
        if not command:
            continue
        if command.startswith('#'):
            # Parse comment magic
            match = OPTION_RE.match(command)
            if match:
                option, arg = match.group('option'), match.group('arg')
                if option == 'prompt':
                    prompt_template = arg
                elif option == 'shell':
                    shell = arg
                elif option == 'alias':
                    aliases.append(arg)
                elif option == 'env':
                    envvars.append(arg)
                elif option == 'speed':
                    speed = int(arg)
            continue
        magictype(command, shell, prompt_template=prompt_template,
            aliases=aliases, envvars=envvars, speed=speed, test_mode=test_mode)
    prompt = make_prompt_formatter(prompt_template)()
    echo(prompt + ' ', nl=False)
    wait_for(RETURNS)
    secho("FINISHED SESSION", fg='yellow', bold=True)


# Les CLI

@click.version_option(__version__, '--version', '-v')
@click.group(context_settings={'help_option_names': ('-h', '--help')})
def cli():
    """doitlive: A tool for "live" presentations in the terminal

    \b
    Basic:
        1. Create a file called session.sh. Fill it with bash commands.
        2. Run "doitlive play session.sh".
        3. Type like a madman.

    Press Ctrl-C at any time to exit a session.
    To see a demo session, run "doitlive demo".

    You can use --help to get help with subcommands.

    Example: doitlive play --help
    """
    pass


def preview_themes():
    secho('Theme previews:', bold=True)
    echo()
    for name, template in THEMES.items():
        echo('"{}" theme:'.format(name))
        echo(format_prompt(template), nl=False)
        echo(' command arg1 arg2 ... argn')
        echo()

def list_themes():
    secho('Available themes:', bold=True)
    echo(' '.join(THEMES.keys()))


@click.option('--preview', '-p', is_flag=True, default=False,
    help='Preview the available prompt themes.')
@click.option('--list', '-l', is_flag=True, default=False,
    help='List the available prompt themes.')
@cli.command()
def themes(preview, list):
    """Preview the available prompt themes."""
    if preview:
        preview_themes()
    else:
        list_themes()

SHELL_OPTION = click.option('--shell', '-S', metavar='<shell>',
        default='/bin/bash', help='The shell to use.', show_default=True)

SPEED_OPTION = click.option('--speed', '-s', metavar='<int>', default=1,
        help='Typing speed.', show_default=True)

PROMPT_OPTION = click.option('--prompt', '-p', metavar='<prompt_theme>',
        default='default', type=click.Choice(THEMES.keys()),
        help='Prompt theme.',
        show_default=True)

ALIAS_OPTION = click.option('--alias', '-a', metavar='<alias>',
    multiple=True, help='Add a session alias.')

ENVVAR_OPTION = click.option('--envvar', '-e', metavar='<envvar>',
    multiple=True, help='Adds a session variable.')


def _compose(*functions):
    def inner(func1, func2):
        return lambda x: func1(func2(x))
    return functools.reduce(inner, functions)

# Compose the decorators into "bundled" decorators
player_command = _compose(SHELL_OPTION, SPEED_OPTION, PROMPT_OPTION)
recorder_command = _compose(SHELL_OPTION, PROMPT_OPTION, ALIAS_OPTION, ENVVAR_OPTION)

@player_command
@click.argument('session_file', type=click.File('r', encoding='utf-8'))
@cli.command()
def play(session_file, shell, speed, prompt):
    """Play a session file."""
    run(session_file.readlines(),
        shell=shell,
        speed=speed,
        test_mode=TESTING,
        prompt_template=prompt)

DEMO = [
    'echo "Greetings"',
    'echo "This is just a demo session"',
    'echo "For more info, check out the home page..."',
    'echo "http://doitlive.rtfd.org"'
]


@player_command
@cli.command()
def demo(shell, speed, prompt):
    """Run a demo doitlive session."""
    run(DEMO, shell=shell, speed=speed, test_mode=TESTING, prompt_template=prompt)


HEADER_TEMPLATE = """# Recorded with the doitlive recorder
#doitlive shell: {shell}
#doitlive prompt: {prompt}
"""

STOP_COMMAND = 'stop'
PREVIEW_COMMAND = 'P'
UNDO_COMMAND = 'U'

def echo_rec_buffer(commands):
    if commands:
        echo('Current commands in buffer:\n')
        for cmd in commands:
            echo('  ' + cmd)
    else:
        echo('No commands in buffer.')

def run_recorder(shell, prompt, aliases=None, envvars=None):
    commands = []
    prefix = '(' + style('REC', fg='red') + ') '
    while True:
        formatted_prompt = prefix + format_prompt(THEMES[prompt]) + ' '
        command = click.prompt(formatted_prompt, prompt_suffix='').strip()

        if command == STOP_COMMAND:
            break
        elif command == PREVIEW_COMMAND:
            echo_rec_buffer(commands)
        elif command == UNDO_COMMAND:
            if commands and click.confirm('Remove command? "{}"'.format(commands[-1])):
                commands.pop()
                secho('Removed command.', bold=True)
                echo_rec_buffer(commands)
            else:
                echo('No commands in buffer. Doing nothing.')
        else:
            commands.append(command)
            run_command(command, shell=shell,
                aliases=aliases, envvars=envvars, test_mode=TESTING)
    return commands


@recorder_command
@click.argument('session_file', default='session.sh',
    type=click.Path(dir_okay=False, writable=True))
@cli.command()
def record(session_file, shell, prompt, alias, envvar):
    """Record a session file. If no argument is passed, commands are written to
    ./session.sh.

    When you are finished recording, run the "stop" command.
    """
    if os.path.exists(session_file):
        click.confirm(
            'File "{0}" already exists. Overwrite?'.format(session_file),
            abort=True, default=False)

    secho("We'll do it live!", fg='red', bold=True)
    filename = click.format_filename(session_file)
    secho('RECORDING SESSION: {}'.format(filename),
        fg='yellow', bold=True)

    # Instructions
    echo()
    echo('INSTRUCTIONS:')
    echo('Enter ' + style('{}'.format(STOP_COMMAND), bold=True) +
        ' when you are done recording.')
    echo('To preview the commands in the buffer, enter {}.'
        .format(style(PREVIEW_COMMAND, bold=True)))
    echo('To undo the last command in the buffer, enter {}.'
        .format(style(UNDO_COMMAND, bold=True)))
    echo()

    click.pause()
    click.clear()
    cwd = os.getcwd()  # Save cwd

    # Run the recorder
    commands = run_recorder(shell, prompt, aliases=alias, envvars=envvar)

    os.chdir(cwd)  # Reset cwd

    secho("FINISHED RECORDING SESSION", fg='yellow', bold=True)
    secho('Writing to {0}...'.format(filename), fg='cyan')
    with open(session_file, 'w', encoding='utf-8') as fp:
        fp.write(HEADER_TEMPLATE.format(shell=shell, prompt=prompt))
        write_directives(fp, 'alias', alias)
        write_directives(fp, 'env', envvar)
        fp.write('\n')
        fp.write('\n\n'.join(commands))
        fp.write('\n')

    play_cmd = style('doitlive play {}'.format(filename), bold=True)
    echo('Done. Run {} to play back your session.'.format(play_cmd))


if __name__ == '__main__':
    cli()
