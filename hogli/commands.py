"""Command classes for hogli CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import click

from hogli.manifest import get_services_for_command


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    """Execute a shell command."""
    from hogli.manifest import REPO_ROOT

    display = " ".join(command)
    click.echo(f"🚀 {display}")
    try:
        subprocess.run(
            command,
            cwd=REPO_ROOT,
            env={**os.environ, **(env or {})},
            check=True,
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
    """
    lines = []

    # Add main description
    description = cmd_config.get("description", "")
    if description:
        lines.append(description)

    # Add service context if available
    services = get_services_for_command(cmd_name, cmd_config)
    if services:
        lines.append("")
        for svc_name, about in services:
            lines.append(f"{svc_name}: {about}")

    # Add underlying command
    if underlying_cmd:
        lines.append("")
        if " && " in underlying_cmd:  # Composite command
            lines.append(f"Runs: {underlying_cmd}")
        else:
            lines.append(f"Command: {underlying_cmd}")

    return "\n".join(lines)


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

    def register(self, cli_group: click.Group) -> None:
        """Register this command with the CLI group."""
        help_text = self.get_help_text()

        @cli_group.command(self.name, help=help_text)
        def cmd() -> None:
            try:
                self.execute()
            except SystemExit:
                raise

        return cmd


class BinScriptCommand(Command):
    """Command that delegates to a shell script in bin/."""

    def __init__(self, name: str, config: dict, script_path: Path) -> None:
        """Initialize with script path."""
        super().__init__(name, config)
        self.script_path = script_path
        self.allow_extra_args = config.get("allow_extra_args", False)

    def get_underlying_command(self) -> str:
        """Return the script name."""
        return self.script_path.name

    def register(self, cli_group: click.Group) -> None:
        """Register with optional extra args support."""
        help_text = self.get_help_text()

        if self.allow_extra_args:

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

        else:

            @cli_group.command(self.name, help=help_text)
            def cmd() -> None:  # type: ignore
                try:
                    self.execute()
                except SystemExit:
                    raise

        return cmd

    def execute(self, *args: str) -> None:
        """Execute the script."""
        _run([str(self.script_path), *args])


class DirectCommand(Command):
    """Command that executes a direct shell command."""

    def get_underlying_command(self) -> str:
        """Return the shell command."""
        return self.config.get("cmd", "")

    def execute(self, *args: str) -> None:
        """Execute the shell command."""
        cmd_str = self.config.get("cmd", "")
        _run(cmd_str.split())


class CompositeCommand(Command):
    """Command that runs multiple hogli commands in sequence."""

    def get_underlying_command(self) -> str:
        """Return the composed command string."""
        steps = self.config.get("steps", [])
        return f"hogli {' && hogli '.join(steps)}"

    def execute(self, *args: str) -> None:
        """Execute each step in sequence."""
        steps = self.config.get("steps", [])
        for step in steps:
            click.echo(f"✨ Executing: {step}")
            try:
                _run(["hogli", step])
            except SystemExit:
                raise
