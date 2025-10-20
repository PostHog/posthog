"""hogli - Unified developer CLI for PostHog monorepo.

All commands are defined in scripts_manifest.yaml and auto-discovered.
Help output is dynamically generated from the manifest with category grouping.
"""

from __future__ import annotations

from collections import defaultdict

import click

from hogli.commands import BinScriptCommand, CompositeCommand, DirectCommand
from hogli.manifest import REPO_ROOT, load_manifest

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
        from hogli.manifest import (
            get_category_for_command as get_cat_for_cmd,
            get_manifest,
        )

        manifest_obj = get_manifest()
        categories_list = manifest_obj.categories

        # Build a mapping from category key to title
        category_key_to_title = {cat.get("key"): cat.get("title") for cat in categories_list}

        # Group commands by category, storing (key, title) tuple
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for cmd_name, cmd in self.commands.items():
            category_title = get_cat_for_cmd(cmd_name)
            help_text = cmd.get_short_help_str(100) if hasattr(cmd, "get_short_help_str") else (cmd.help or "")

            # Find the key for this title
            category_key = next(
                (key for key, title in category_key_to_title.items() if title == category_title), "commands"
            )
            grouped[(category_key, category_title)].append((cmd_name, help_text))

        # Build category order from the list
        category_order = {idx: cat.get("key") for idx, cat in enumerate(categories_list)}

        def get_category_sort_key(cat_tuple: tuple[str, str]) -> int:
            key = cat_tuple[0]
            if key == "commands":  # Default category goes last
                return len(category_order) + 1
            return next((idx for idx, k in category_order.items() if k == key), 999)

        sorted_categories = sorted(grouped.items(), key=get_category_sort_key)

        # Format each category section
        for (_category_key, category_title), commands in sorted_categories:
            rows = [(cmd_name, help_text) for cmd_name, help_text in sorted(commands, key=lambda x: x[0])]
            if rows:
                with formatter.section(category_title):
                    formatter.write_dl(rows)


@click.group(cls=CategorizedGroup, help="Unified developer experience for the PostHog monorepo.")
def cli() -> None:
    """hogli - Developer CLI for PostHog."""
    pass


@cli.command(name="concepts", help="Show services and infrastructure concepts")
def concepts() -> None:
    """Display infrastructure concepts and services with descriptions and related commands."""
    from hogli.manifest import get_services_for_command

    manifest = load_manifest()
    services_dict = manifest.get("metadata", {}).get("services", {})

    if not services_dict:
        click.echo("No services found in manifest.")
        return

    # Build a reverse mapping: service_name -> service_key
    service_name_to_key = {svc_info.get("name", key): key for key, svc_info in services_dict.items()}

    # Build a map of service_key -> list of commands that use it
    service_commands: dict[str, set[str]] = {svc_key: set() for svc_key in services_dict}

    # Scan all commands for explicit services or prefix matching
    for category, scripts in manifest.items():
        if category == "metadata" or not isinstance(scripts, dict):
            continue
        for cmd_name, config in scripts.items():
            if not isinstance(config, dict):
                continue

            # Get services for this command
            services = get_services_for_command(cmd_name, config)
            for svc_name, _ in services:
                svc_key = service_name_to_key.get(svc_name)
                if svc_key:
                    service_commands[svc_key].add(cmd_name)

    click.echo("\nInfrastructure Concepts:\n")
    for service_key in sorted(services_dict.keys()):
        service_info = services_dict[service_key]
        name = service_info.get("name", service_key)
        about = service_info.get("about", "No description")
        click.echo(f"  {name}")
        click.echo(f"    {about}")

        commands = service_commands[service_key]
        if commands:
            click.echo(f"    Commands: {', '.join(sorted(commands))}")
        click.echo()


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

            # Determine command type
            bin_script = config.get("bin_script")
            steps = config.get("steps")
            cmd = config.get("cmd")

            if not (bin_script or steps or cmd):
                continue

            # Handle composition (steps field)
            if steps:
                command = CompositeCommand(cli_name, config)
                command.register(cli)
                continue

            # Handle direct commands (cmd field)
            if cmd:
                command = DirectCommand(cli_name, config)
                command.register(cli)
                continue

            # Handle bin_script delegation
            if bin_script:
                script_path = BIN_DIR / bin_script
                if not script_path.exists():
                    continue

                command = BinScriptCommand(cli_name, config, script_path)
                command.register(cli)


# Register all script commands from manifest before app runs
_register_script_commands()


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
