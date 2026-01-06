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

import subprocess

import click

# Import commands from other modules to register them
from hogli import doctor  # noqa: F401
from hogli.core.cli import cli


def _get_committed_python_files(base: str) -> list[str]:
    """Get Python files in commits between base and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}..HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().split("\n") if f.endswith(".py") and f]


def _has_uncommitted_changes() -> bool:
    """Check for staged or unstaged changes."""
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    return bool(result.stdout.strip())


@cli.command(name="test:python-affected", help="Run Python tests affected by committed changes")
@click.option("--base", default="origin/master", help="Base branch/commit to compare against")
@click.option("--dry-run", is_flag=True, help="Show affected tests without running them")
@click.pass_context
def test_python_affected(ctx: click.Context, base: str, dry_run: bool) -> None:
    """Run only Python tests affected by your committed changes.

    Analyzes imports to find tests affected by commits between base and HEAD.
    Best for unit tests that directly import code. API/integration tests
    using URL routing may not be detected.

    Examples:
        hogli test:python-affected                  # vs origin/master
        hogli test:python-affected --base HEAD~3   # vs 3 commits ago
        hogli test:python-affected --dry-run       # show what would run
    """
    import snob_lib

    if _has_uncommitted_changes():
        click.secho("Warning: uncommitted changes won't be tested. Commit first.", fg="yellow")
        click.echo("")

    changed_files = _get_committed_python_files(base)
    if not changed_files:
        click.echo("No Python files changed in commits.")
        ctx.exit(0)

    click.echo(f"Changed files ({len(changed_files)}):")
    for f in sorted(changed_files)[:10]:
        click.echo(f"  {f}")
    if len(changed_files) > 10:
        click.echo(f"  ... and {len(changed_files) - 10} more")
    click.echo("")

    click.echo("Analyzing imports...")
    affected_tests = snob_lib.get_tests(changed_files)
    if not affected_tests:
        click.echo("No affected tests found.")
        ctx.exit(0)

    click.echo(f"Found {len(affected_tests)} affected test file(s)")
    click.echo("")

    if dry_run:
        for test in sorted(affected_tests):
            click.echo(test)
        ctx.exit(0)

    cmd = ["pytest", "-m", "not integration", *affected_tests]
    result = subprocess.run(cmd)
    ctx.exit(result.returncode)
