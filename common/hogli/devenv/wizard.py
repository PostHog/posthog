"""Interactive wizard for developer environment setup.

Guides users through selecting intents and generates mprocs.yaml directly.
"""

from __future__ import annotations

from pathlib import Path

import click

from .generator import (
    DevenvConfig,
    MprocsGenerator,
    get_generated_mprocs_path,
    get_main_repo_from_worktree,
    load_devenv_config,
)
from .registry import create_mprocs_registry
from .resolver import IntentMap, IntentResolver


def _choose_config_location(local_path: Path) -> Path:
    """Ask where to save config if in a worktree."""
    main_repo = get_main_repo_from_worktree()
    if not main_repo:
        return local_path  # Not in a worktree

    main_path = main_repo / ".posthog" / ".generated" / "mprocs.yaml"

    click.echo("You're in a git worktree. Where should the config be saved?")
    click.echo("  1. This worktree only")
    click.echo("  2. Main repo (symlinked here, shared across worktrees)")
    click.echo("")

    choice = click.prompt("Choice", type=click.Choice(["1", "2"]), default="2")
    if choice == "1":
        return local_path

    # Create symlink from worktree to main repo (config file created after this)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    # exists() is False for broken symlinks, so check both
    if local_path.exists() or local_path.is_symlink():
        local_path.unlink()
    local_path.symlink_to(main_path)
    return main_path


def run_setup_wizard(intent_map: IntentMap, log_to_files: bool = False) -> DevenvConfig | None:
    """Run the setup wizard.

    Args:
        intent_map: The intent map
        log_to_files: Whether to log process output to /tmp/posthog-*.log files

    Returns:
        The created config, or None if cancelled
    """
    registry = create_mprocs_registry()
    resolver = IntentResolver(intent_map, registry)
    local_path = get_generated_mprocs_path()

    click.echo("")
    click.echo(click.style("PostHog Developer Environment Setup", fg="green", bold=True))
    click.echo("")
    click.echo("Configure which services to start based on the products you're working on.")
    click.echo("")

    # Check for existing config (follows symlinks)
    existing = load_devenv_config(local_path)
    if existing:
        if local_path.is_symlink():
            click.echo("Found config (symlinked from main repo):")
        else:
            click.echo("Found existing config:")
        _show_config_summary(existing)
        click.echo("")
        if not click.confirm("Replace it?", default=True):
            return None
        output_path = local_path.resolve()  # Follow symlink for actual save location
    else:
        # No config - ask where to save if in worktree
        output_path = _choose_config_location(local_path)

    # Select products/intents
    config = _setup_from_intents(intent_map)

    # Ask about overrides
    config = _configure_overrides(config, registry, resolver)

    # Set log mode if requested
    config.log_to_files = log_to_files

    # Show summary
    click.echo("")
    click.echo(click.style("Summary", fg="cyan", bold=True))
    click.echo("-" * 40)
    _show_config_summary(config)

    # Show what would be started
    resolved = resolver.resolve(
        config.intents,
        include_units=config.include_units,
        exclude_units=config.exclude_units,
        skip_autostart=config.skip_autostart,
        enable_autostart=config.enable_autostart,
    )
    click.echo("")
    click.echo(f"This will start {len(resolved.units)} processes.")
    click.echo("")

    if not click.confirm("Save this configuration?", default=True):
        click.echo("Cancelled.")
        return None

    # Generate and save mprocs config
    generator = MprocsGenerator(registry)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generator.generate_and_save(resolved, output_path, config)

    click.echo("")
    click.echo(click.style("✓ Config saved!", fg="green"))
    click.echo(f"  Location: {output_path}")
    click.echo("")
    click.echo("Run 'hogli start' to start.")

    return config


def _show_config_summary(config: DevenvConfig) -> None:
    """Show config summary."""
    if config.intents:
        click.echo(f"  Products: {', '.join(config.intents)}")

    if config.include_units:
        click.echo(f"  Include: {', '.join(config.include_units)}")
    if config.exclude_units:
        click.echo(f"  Exclude: {', '.join(config.exclude_units)}")
    if config.skip_autostart:
        click.echo(f"  Manual start: {', '.join(config.skip_autostart)}")
    if config.enable_autostart:
        click.echo(f"  Auto-start: {', '.join(config.enable_autostart)}")
    if config.log_to_files:
        click.echo("  Log mode: /tmp/posthog-*.log")


def _setup_from_intents(intent_map: IntentMap) -> DevenvConfig:
    """Set up by selecting specific intents."""
    select_all = "all"
    click.echo("")
    click.echo(click.style("Products", fg="cyan"))
    click.echo(f"Select products (comma-separated numbers, or '{select_all}').")
    click.echo("")

    intents = list(intent_map.intents.items())
    for i, (name, intent) in enumerate(intents, 1):
        click.echo(f"  {i:2}. {name} - {intent.description}")

    click.echo("")

    selection = click.prompt(f"Enter numbers (e.g., 1,3,5) or '{select_all}'", default="1")

    selected_intents = []
    if selection.strip().lower() == select_all:
        selected_intents = [name for name, _ in intents]
    else:
        try:
            indices = [int(x.strip()) for x in selection.split(",")]
            for idx in indices:
                if 1 <= idx <= len(intents):
                    selected_intents.append(intents[idx - 1][0])
        except ValueError:
            click.echo("Invalid selection, using product_analytics.")
            selected_intents = ["product_analytics"]

    if not selected_intents:
        selected_intents = ["product_analytics"]

    return DevenvConfig(intents=selected_intents)


def _configure_overrides(config: DevenvConfig, registry, resolver: IntentResolver) -> DevenvConfig:
    """Configure overrides."""
    # Show what will be started
    resolved = resolver.resolve(config.intents)
    units_list = sorted(resolved.units)

    # Find manual-start processes
    manual_start = set()
    for unit in units_list:
        proc_config = registry.get_process_config(unit)
        if proc_config.get("autostart") is False:
            manual_start.add(unit)

    click.echo("")
    click.echo(click.style("Processes that will start:", fg="cyan"))
    for unit in units_list:
        if unit in manual_start:
            click.echo(f"  {unit} (manual start)")
        else:
            click.echo(f"  {unit}")

    click.echo("")
    click.echo("Units to exclude (enter names from above, or blank to skip):")
    exclude = click.prompt("Comma-separated", default="")
    if exclude.strip():
        config.exclude_units = [u.strip() for u in exclude.split(",") if u.strip()]

    # Ask about manual-start processes (those with ask_skip: true)
    ask_skip_processes = registry.get_ask_skip_processes()
    for process_name in ask_skip_processes:
        click.echo("")
        if click.confirm(f"Auto-start {process_name}?", default=False):
            config.enable_autostart.append(process_name)

    return config
