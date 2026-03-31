"""hogli - Unified developer CLI for PostHog monorepo.

All commands are defined in scripts_manifest.yaml and auto-discovered.
Help output is dynamically generated from the manifest with category grouping.
"""

from __future__ import annotations

import os
import sys
import time as _time
import shutil
import platform
from collections import defaultdict
from typing import Any

import click
from hogli import telemetry
from hogli.core.command_types import BinScriptCommand, CompositeCommand, DirectCommand, HogliCommand
from hogli.core.manifest import REPO_ROOT, get_category_for_command, load_manifest

BIN_DIR = REPO_ROOT / "bin"


class CategorizedGroup(click.Group):
    """Custom Click group that formats help output like git help with categories.

    Overrides ``invoke`` to wrap every subcommand execution with telemetry
    tracking (timing, exit code) using ``ctx.meta`` for state instead of a
    module-level singleton.
    """

    def invoke(self, ctx: click.Context) -> Any:
        ctx.meta["hogli.start_time"] = _time.monotonic()
        ctx.meta["hogli.has_extra_argv"] = len(sys.argv) > 2
        exit_code = 0
        try:
            return super().invoke(ctx)
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else (1 if e.code else 0)
            raise
        except KeyboardInterrupt:
            exit_code = 130
            raise
        except Exception:
            exit_code = 1
            raise
        finally:
            _fire_telemetry(ctx, exit_code)
            telemetry.flush()

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        """Format commands grouped by category, git-style with extends tree."""
        from hogli.core.manifest import (
            get_category_for_command as get_cat_for_cmd,
            get_manifest,
        )

        manifest_obj = get_manifest()
        categories_list = manifest_obj.categories

        # Build a mapping from category key to title
        category_key_to_title = {cat.get("key"): cat.get("title") for cat in categories_list}

        # Set of commands that extend others (will be rendered under their parent)
        child_commands = {child for parent in self.commands for child in manifest_obj.get_children_for_command(parent)}

        # Group commands by category, storing (key, title) tuple
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for cmd_name, cmd in self.commands.items():
            # Skip hidden commands (they're still callable, just not shown in help)
            hogli_config = getattr(cmd, "hogli_config", {})
            if hogli_config.get("hidden", False):
                continue

            # Skip child commands - they'll be rendered under their parent
            if cmd_name in child_commands:
                continue

            category_title = get_cat_for_cmd(cmd_name)
            help_text = cmd.get_short_help_str(100) if hasattr(cmd, "get_short_help_str") else (cmd.help or "")

            # Find the key for this title
            category_key = next(
                (key for key, title in category_key_to_title.items() if title == category_title), "commands"
            )
            grouped[(category_key, category_title)].append((cmd_name, help_text))

        # Build category order from the list
        category_order = {idx: cat.get("key") for idx, cat in enumerate(categories_list)}

        def get_category_sort_key(item: tuple[tuple[str, str], list[tuple[str, str]]]) -> int:
            cat_tuple, _commands = item
            key = cat_tuple[0]
            if key == "commands":  # Default category goes last
                return len(category_order) + 1
            return next((idx for idx, k in category_order.items() if k == key), 999)

        sorted_categories = sorted(grouped.items(), key=get_category_sort_key)

        # Format each category section
        for (_category_key, category_title), commands in sorted_categories:
            rows: list[tuple[str, str]] = []
            for cmd_name, help_text in sorted(commands, key=lambda x: x[0]):
                rows.append((cmd_name, help_text))
                # Render children indented under parent
                for child in manifest_obj.get_children_for_command(cmd_name):
                    suffix = child.removeprefix(cmd_name)  # e.g., ":minimal"
                    rows.append((f"  └─ {suffix}", ""))
            if rows:
                with formatter.section(category_title):
                    formatter.write_dl(rows)


def _auto_update_manifest() -> None:
    """Automatically update manifest with missing entries."""
    from hogli.core.validate import auto_update_manifest

    added = auto_update_manifest()
    if added:
        click.secho(
            f"ℹ️  Auto-added to manifest: {', '.join(sorted(added))}",
            fg="blue",
            err=True,
        )


@click.group(
    cls=CategorizedGroup,
    help="Unified developer experience for the PostHog monorepo.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """hogli - Developer CLI for PostHog."""
    # Auto-update manifest on every invocation (but skip for meta:check and git hooks)
    # Skip during git hooks to prevent manifest modifications during lint-staged execution
    in_git_hook = os.environ.get("GIT_DIR") is not None or os.environ.get("HUSKY") is not None
    if ctx.invoked_subcommand not in {"meta:check", "help"} and not in_git_hook:
        _auto_update_manifest()
        if ctx.invoked_subcommand not in {"telemetry:off", "telemetry:status"}:
            telemetry.show_first_run_notice_if_needed()

    # Fire early so long-running commands (e.g. hogli start) are always counted
    # even if the process is killed without a clean exit.
    if ctx.invoked_subcommand and ctx.invoked_subcommand != "telemetry:off":
        telemetry.track(
            "command_started", {"command": ctx.invoked_subcommand, **_env_properties(ctx.invoked_subcommand)}
        )


@cli.command(name="quickstart", help="Show getting started with PostHog development")
def quickstart() -> None:
    """Display essential commands for getting up and running."""
    click.echo("")
    click.echo(click.style("🚀 PostHog Development Quickstart", fg="green", bold=True))
    click.echo("")
    click.echo("Get PostHog running locally:")
    click.echo("")
    click.echo("  hogli start")
    click.echo("")
    click.echo("  That's it! Starts Docker, runs migrations, launches all services.")
    click.echo("  Opens http://localhost:8010 when ready.")
    click.echo("")
    click.echo("Optional:")
    click.echo("  hogli dev:setup               configure which services to run")
    click.echo("  hogli dev:demo-data           generate test data")
    click.echo("  hogli dev:reset               full reset & reload")
    click.echo("")
    click.echo("Common commands:")
    click.echo("  hogli format                  format all code")
    click.echo("  hogli lint                    run quality checks")
    click.echo("  hogli test:python <path>      run Python tests")
    click.echo("  hogli test:js <path>          run JS tests")
    click.echo("")
    click.echo("For full command list:")
    click.echo("  hogli --help")
    click.echo("")


@cli.command(name="meta:check", help="Validate manifest against bin scripts (for CI)")
def meta_check() -> None:
    """Validate that all bin scripts are in the manifest."""
    from hogli.core.validate import find_missing_manifest_entries

    missing = find_missing_manifest_entries()

    if not missing:
        click.echo("✓ All bin scripts are in the manifest")
        return

    click.echo(f"✗ Found {len(missing)} bin script(s) not in manifest:")
    for script in sorted(missing):
        click.echo(f"  - {script}")

    raise SystemExit(1)


@cli.command(name="meta:concepts", help="Show services and infrastructure concepts")
def concepts() -> None:
    """Display infrastructure concepts and services with descriptions and related commands."""
    from hogli.core.manifest import get_services_for_command

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
            hogli = config.get("hogli")

            if not (bin_script or steps or cmd or hogli):
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

            # Handle hogli wrapper commands (hogli field)
            if hogli:
                command = HogliCommand(cli_name, config)
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

# Import developer commands module to register any @cli.command() decorated functions
try:
    import hogli.commands  # noqa: F401
except ImportError:
    pass  # No developer commands yet


def _infer_process_manager(command: str | None) -> str | None:
    """Infer the active process manager for telemetry."""
    pm = os.environ.get("HOGLI_PROCESS_MANAGER")
    if pm:
        return os.path.basename(pm)

    if command == "start":
        return "mprocs" if "--mprocs" in sys.argv[2:] else "phrocs"

    return None


def _env_properties(command: str | None = None) -> dict[str, Any]:
    """Static environment properties shared across telemetry events."""
    ci_env_vars = ("CI", "GITHUB_ACTIONS", "JENKINS_URL", "GITLAB_CI", "CIRCLECI", "BUILDKITE")
    return {
        "terminal_width": shutil.get_terminal_size().columns,
        "os": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "is_ci": any(os.environ.get(v) for v in ci_env_vars),
        "has_devenv_config": (REPO_ROOT / ".posthog" / ".generated" / "mprocs.yaml").exists(),
        "in_flox": os.environ.get("FLOX_ENV") is not None,
        "is_worktree": (REPO_ROOT / ".git").is_file(),
        "process_manager": _infer_process_manager(command),
    }


def _fire_telemetry(ctx: click.Context, exit_code: int) -> None:
    """Send a command_completed telemetry event. Never raises."""
    command = ctx.invoked_subcommand
    # Skip when CLI itself errors before reaching a subcommand (e.g. bad flag)
    if command is None and exit_code != 0:
        return
    try:
        start_time: float = ctx.meta.get("hogli.start_time", 0.0)
        duration_s = _time.monotonic() - start_time
        props: dict[str, Any] = {
            "command": command,
            "command_category": get_category_for_command(command) if command else None,
            "duration_s": round(duration_s, 3),
            "exit_code": exit_code,
            "has_extra_argv": ctx.meta.get("hogli.has_extra_argv", False),
            **_env_properties(command),
        }
        # Merge devenv-specific properties (set by dev:generate)
        devenv = ctx.meta.get("hogli.devenv")
        if devenv:
            props.update(devenv)
        telemetry.track("command_completed", props)
    except Exception:
        pass


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
