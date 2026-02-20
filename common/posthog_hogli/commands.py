"""Developer Click commands for PostHog workflows.

This is the extension point for adding new Click commands to hogli.
Add your @cli.command() decorated functions here as an alternative to shell scripts.

They auto-register with hogli and appear in `hogli --help` automatically.

Example:
    ```python
    import click
    from hogli.cli import cli

    @cli.command(name="my:command", help="Does something useful")
    @click.argument('path', type=click.Path())
    @click.option('--flag', is_flag=True, help='Enable feature')
    def my_command(path, flag):
        '''Command implementation.'''
        # Your Python logic here
        click.echo(f"Processing {path}")
    ```

Guidelines:
- Use Click decorators for arguments and options
- Import cli group from hogli.cli (the framework in tools/hogli/)
- Name commands with colons for grouping (e.g., 'test:python', 'db:migrate')
- Add helpful docstrings - they become the command help text
- Prefer Python Click commands over shell scripts for better type safety

For simple shell commands or bin script delegation, use hogli.yaml instead.
"""

from __future__ import annotations

# Side-effect imports: these modules use @cli.command() decorators that register
# commands with the CLI group when imported. The imports appear unused but are required.
from . import (  # noqa: F401
    doctor,
    migrations,
    product,
)
from .devenv import cli as devenv_cli  # noqa: F401
