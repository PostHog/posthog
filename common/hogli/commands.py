"""Developer Click commands for PostHog workflows.

This is the extension point for adding new Click commands to hogli.
Add your @cli.command() decorated functions here as an alternative to shell scripts.

They auto-register with hogli and appear in `hogli --help` automatically.

Example:
    ```python
    import click
    from common.hogli.core.cli import cli

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
- Import cli group from common.hogli.core.cli
- Name commands with colons for grouping (e.g., 'test:python', 'db:migrate')
- Add helpful docstrings - they become the command help text
- Prefer Python Click commands over shell scripts for better type safety

For simple shell commands or bin script delegation, use manifest.yaml instead.
"""

from __future__ import annotations

# Add your Click commands below this line
# Example command (remove or keep as reference):
# @cli.command(name="example:hello", help="Example Click command")
# @click.argument('name')
# @click.option('--greeting', default='Hello', help='Greeting to use')
# def example_hello(name: str, greeting: str) -> None:
#     """Say hello to someone."""
#     click.echo(f"{greeting}, {name}!")
# Import commands from other modules to register them
from hogli import doctor  # noqa: F401
