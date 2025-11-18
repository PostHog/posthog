"""Command classes for hogli CLI."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

import click
from hogli.core.manifest import get_services_for_command


def _run(command: list[str] | str, *, env: dict[str, str] | None = None, shell: bool = False) -> None:
    """Execute a shell command."""
    from hogli.core.manifest import REPO_ROOT

    if isinstance(command, list):
        display = " ".join(command)
    else:
        display = command
    click.echo(f"🚀 {display}")
    try:
        subprocess.run(
            command,
            cwd=REPO_ROOT,
            env={**os.environ, **(env or {})},
            check=True,
            shell=shell,
        )
    except subprocess.CalledProcessError as e:
        click.echo(click.style(f"💥 Command failed: {display}", fg="red", bold=True), err=True)
        raise SystemExit(1) from e


def _format_command_help(cmd_name: str, cmd_config: dict, underlying_cmd: str) -> str:
    """Format help text with service context and underlying command.

    Returns formatted help text with:
    - Original description
    - Service info if available
    - Underlying command being executed

    Note: Click will rewrap long lines, but we add paragraph breaks between
    services for better readability.
    """
    parts = []

    # Add main description
    if description := cmd_config.get("description", ""):
        parts.append(description)

    # Add service context if available
    services = get_services_for_command(cmd_name, cmd_config)
    if services:
        parts.append("Uses:")
        # Add each service as a separate paragraph to force line breaks
        for svc_name, about in services:
            parts.append(f"• {svc_name}: {about}")

    # Add underlying command
    if underlying_cmd:
        parts.append(f"Executes: {underlying_cmd}")

    # Join with double newlines to create paragraph breaks
    return "\n\n".join(parts)


class Command:
    """Base class for CLI commands."""

    def __init__(self, name: str, config: dict) -> None:
        """Initialize command with configuration."""
        self.name = name
        self.config = config
        self.description = config.get("description", "")

    def get_underlying_command(self) -> str:
        """Get the underlying command being executed. Override in subclasses."""
        return ""

    def get_help_text(self) -> str:
        """Generate formatted help text with service context and underlying command."""
        return _format_command_help(self.name, self.config, self.get_underlying_command())

    def execute(self, *args: str) -> None:
        """Override in subclasses."""
        raise NotImplementedError("Subclasses must implement execute()")

    def register(self, cli_group: click.Group) -> Any:
        """Register this command with the CLI group."""
        help_text = self.get_help_text()

        @cli_group.command(self.name, help=help_text)
        def cmd() -> None:
            try:
                self.execute()
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd


class BinScriptCommand(Command):
    """Command that delegates to a shell script in bin/."""

    def __init__(self, name: str, config: dict, script_path: Path) -> None:
        """Initialize with script path."""
        super().__init__(name, config)
        self.script_path = script_path

    def get_underlying_command(self) -> str:
        """Return the script path relative to repo root."""
        from hogli.core.manifest import REPO_ROOT

        try:
            return str(self.script_path.relative_to(REPO_ROOT))
        except ValueError:
            # If not relative to repo root, just return the name
            return self.script_path.name

    def register(self, cli_group: click.Group) -> Any:
        """Register command with extra args support."""
        help_text = self.get_help_text()

        @cli_group.command(
            self.name,
            help=help_text,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.pass_context
        def cmd(ctx: click.Context) -> None:
            try:
                self.execute(*ctx.args)
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str) -> None:
        """Execute the script with any passed arguments."""
        _run([str(self.script_path), *args])


class DirectCommand(Command):
    """Command that executes a direct shell command."""

    def get_underlying_command(self) -> str:
        """Return the shell command."""
        return self.config.get("cmd", "")

    def register(self, cli_group: click.Group) -> Any:
        """Register command with extra args support."""
        help_text = self.get_help_text()

        @cli_group.command(
            self.name,
            help=help_text,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.pass_context
        def cmd(ctx: click.Context) -> None:
            try:
                self.execute(*ctx.args)
            except SystemExit:
                raise

        # Store config on the Click command for visibility filtering
        cmd.hogli_config = self.config  # type: ignore[attr-defined]
        return cmd

    def execute(self, *args: str) -> None:
        """Execute the shell command with any passed arguments."""
        cmd_str = self.config.get("cmd", "")
        # Use shell=True if command contains operators like && or ||
        has_operators = " && " in cmd_str or " || " in cmd_str
        if has_operators:
            # Append args to the command string when using shell
            # Use shlex.quote() to safely escape arguments for shell execution
            if args:
                escaped_args = " ".join(shlex.quote(arg) for arg in args)
                cmd_str = f"{cmd_str} {escaped_args}"
            _run(cmd_str, shell=True)
        else:
            # Use list format for simple commands without shell operators
            # Use shlex.split() to properly handle quoted arguments
            _run([*shlex.split(cmd_str), *args])


class CompositeCommand(Command):
    """Command that runs multiple hogli commands in sequence."""

    def get_underlying_command(self) -> str:
        """Return the composed command string."""
        steps = self.config.get("steps", [])
        return f"hogli {' && hogli '.join(steps)}"

    def execute(self, *args: str) -> None:
        """Execute each step in sequence."""
        from hogli.core.manifest import REPO_ROOT

        steps = self.config.get("steps", [])
        bin_hogli = str(REPO_ROOT / "bin" / "hogli")

        for step in steps:
            click.echo(f"✨ Executing: {step}")
            try:
                # Use bin/hogli for both Flox and non-Flox compatibility
                _run([bin_hogli, step])
            except SystemExit:
                raise
