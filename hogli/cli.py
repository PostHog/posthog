"""hogli - Unified developer CLI for PostHog monorepo.

All commands are defined in scripts_manifest.yaml and auto-discovered.
Help output is dynamically generated from the manifest with category grouping.
"""

from __future__ import annotations

import os
import subprocess
from collections import defaultdict
from pathlib import Path

import click

from hogli.manifest import REPO_ROOT, get_category_for_command, get_services_for_command, load_manifest

HEDGEHOG_ART = r"""


                           00     0
                      000F  F0FF  0000  00
                000FF 00  FF00  FFF0 FF F0F
                 FF   000         00   00 0F 00
           FF00FF000                        000
             F0                               F
          00F0                                00
        FFF0                   0FFFF   FFFFFFF0F
          00                  0F    FF         00
        00                     0F               0F
      FFFF0                      F0       0F0     FFF
        F0                      00         0         F000
       0F                      F0                     F00
      00FF0                   F0                     F0
         F                  FF                000FFFF
        0F00              FF                  000
        00F0           FFF                0FF
          F       FFFFF         0    00 FFF
          0FF00FF               00   0F0  FF
             00    00000000FFFFF00F   0FF0  000
              0FFFF00000000       0FF   00FF00
                                     FFF0
"""

BIN_DIR = REPO_ROOT / "bin"


class CategorizedGroup(click.Group):
    """Custom Click group that formats help output like git help with categories."""

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format commands grouped by category, git-style."""
        manifest = load_manifest()
        metadata = manifest.get("metadata", {}).get("categories", {})

        # Group commands by category
        grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for cmd_name, cmd in self.commands.items():
            category = get_category_for_command(cmd_name)
            help_text = cmd.get_short_help_str(100) if hasattr(cmd, "get_short_help_str") else (cmd.help or "")
            grouped[category].append((cmd_name, help_text))

        # Sort categories by their order in metadata
        def get_category_order(category: str) -> int:
            if category == "commands":  # Default category
                return 999
            return metadata.get(category, {}).get("order", 999)

        sorted_categories = sorted(grouped.items(), key=lambda x: get_category_order(x[0]))

        # Format each category section
        for category, commands in sorted_categories:
            # Get category title from metadata
            if category == "commands":
                category_title = "commands"
            else:
                category_title = metadata.get(category, {}).get("title", category.replace("_", " "))

            # Format commands in this category
            rows = []
            for cmd_name in sorted(c[0] for c in commands):
                cmd = self.commands[cmd_name]
                help_text = cmd.get_short_help_str(100) if hasattr(cmd, "get_short_help_str") else (cmd.help or "")
                rows.append((cmd_name, help_text))

            if rows:
                with formatter.section(category_title):
                    formatter.write_dl(rows)


@click.group(cls=CategorizedGroup, help="Unified developer experience for the PostHog monorepo.")
def cli() -> None:
    """hogli - Developer CLI for PostHog."""
    pass


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


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    """Execute a shell command."""
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


def _register_script_commands() -> None:
    """Dynamically register commands from scripts_manifest.yaml.

    Supports three types of entries:
    1. bin_script: Delegate to a shell script
    2. steps: Compose multiple hogli commands in sequence
    3. cmd: Execute a direct shell command
    """
    manifest = load_manifest()
    if not manifest:
        return

    for _category, scripts in manifest.items():
        if not isinstance(scripts, dict):
            continue

        for cli_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            description = config.get("description", "")
            allow_extra_args = config.get("allow_extra_args", False)

            # Determine command type
            bin_script = config.get("bin_script")
            steps = config.get("steps")  # List of hogli commands to compose
            cmd = config.get("cmd")  # Direct shell command

            if not (bin_script or steps or cmd):
                # No command specified, skip
                continue

            # Handle composition (steps field)
            if steps:

                def make_steps_command(cmd_name: str, step_list: list[str], desc: str, cfg: dict) -> callable:
                    underlying = f"hogli {' && hogli '.join(step_list)}"
                    help_text = _format_command_help(cmd_name, cfg, underlying)

                    @cli.command(cmd_name, help=help_text)
                    def command() -> None:
                        """Composite hogli command."""
                        for step in step_list:
                            click.echo(f"✨ Executing: {step}")
                            try:
                                _run(["hogli", step])
                            except SystemExit:
                                raise

                    return command

                make_steps_command(cli_name, steps, description, config)
                continue

            # Handle direct commands (cmd field)
            if cmd:

                def make_cmd_command(cmd_name: str, shell_cmd: str, desc: str, cfg: dict) -> callable:
                    help_text = _format_command_help(cmd_name, cfg, shell_cmd)

                    @cli.command(cmd_name, help=help_text)
                    def command() -> None:
                        """Direct shell command."""
                        try:
                            _run(shell_cmd.split())
                        except SystemExit:
                            raise

                    return command

                make_cmd_command(cli_name, cmd, description, config)
                continue

            # Handle bin_script delegation (original behavior)
            if bin_script:
                script_path = BIN_DIR / bin_script
                if not script_path.exists():
                    continue

                def make_command(name: str, path: Path, desc: str, extra_args: bool, cfg: dict) -> callable:
                    help_text = _format_command_help(name, cfg, path.name)
                    if extra_args:

                        @cli.command(
                            name,
                            help=help_text,
                            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
                        )
                        @click.pass_context
                        def command(ctx: click.Context) -> None:
                            """Dynamic command from bin/ script."""
                            try:
                                _run([str(path), *ctx.args])
                            except SystemExit:
                                raise

                    else:

                        @cli.command(name, help=help_text)
                        def command() -> None:
                            """Dynamic command from bin/ script."""
                            try:
                                _run([str(path)])
                            except SystemExit:
                                raise

                    return command

                make_command(cli_name, script_path, description, allow_extra_args, config)


# Register all script commands from manifest before app runs
_register_script_commands()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
