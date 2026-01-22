"""CLI commands for intent-based developer environment.

Provides hogli dev:* commands for managing the development environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from hogli.core.cli import cli

from .generator import DevenvConfig, MprocsGenerator, get_generated_mprocs_path, load_devenv_config
from .registry import create_mprocs_registry
from .resolver import IntentResolver, load_intent_map


def _get_repo_root() -> Path:
    """Get repository root path."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def _create_resolver() -> IntentResolver:
    """Create an IntentResolver with the default intent map and mprocs registry."""
    intent_map = load_intent_map()
    registry = create_mprocs_registry()
    return IntentResolver(intent_map, registry)


def _resolve_from_config(resolver: IntentResolver, config: DevenvConfig) -> tuple:
    """Resolve intents from a DevenvConfig.

    Returns:
        Tuple of (resolved_environment, intents_list)
    """
    if config.preset:
        preset_obj = resolver.intent_map.presets.get(config.preset)
        if not preset_obj:
            raise ValueError(f"Unknown preset '{config.preset}'")

        if preset_obj.all_intents:
            intents = list(resolver.intent_map.intents.keys())
        else:
            intents = preset_obj.intents.copy()

        include_caps = list(preset_obj.include_capabilities) or None
    else:
        intents = config.intents.copy()
        include_caps = None

    resolved = resolver.resolve(
        intents,
        include_units=config.include_units,
        exclude_units=config.exclude_units,
        include_capabilities=include_caps,
        skip_autostart=config.skip_autostart,
    )

    return resolved, intents


@cli.command(name="dev:start", help="Start dev environment based on your config")
@click.option(
    "--with",
    "with_intents",
    multiple=True,
    help="Temporarily add intent(s) to this run",
)
@click.option(
    "--without",
    "without_units",
    multiple=True,
    help="Temporarily exclude unit(s) from this run (e.g., --without typegen)",
)
@click.option(
    "--preset",
    help="Use a preset instead of saved config (minimal, backend, replay, ai, full)",
)
@click.option(
    "--explain",
    is_flag=True,
    help="Show what would be started without actually starting",
)
def dev_start(
    with_intents: tuple[str, ...],
    without_units: tuple[str, ...],
    preset: str | None,
    explain: bool,
) -> None:
    """Start development environment based on saved config or preset.

    Uses config from .posthog/.generated/mprocs.yaml or prompts to create one.
    """
    try:
        resolver = _create_resolver()
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Are you in the PostHog repository root?", err=True)
        raise SystemExit(1)

    output_path = get_generated_mprocs_path()

    # Determine config to use
    if preset:
        # Use preset directly, merging any additional intents
        try:
            preset_obj = resolver.intent_map.presets[preset]
        except KeyError:
            available = ", ".join(sorted(resolver.intent_map.presets.keys()))
            click.echo(f"Error: Unknown preset '{preset}'. Available: {available}", err=True)
            raise SystemExit(1)

        if preset_obj.all_intents:
            intents = list(resolver.intent_map.intents.keys())
        else:
            intents = preset_obj.intents.copy()

        # Merge additional intents from --with
        intents.extend(with_intents)

        source_config = DevenvConfig(
            preset=preset,
            exclude_units=list(without_units),
        )

        try:
            resolved = resolver.resolve(
                intents,
                exclude_units=list(without_units),
                include_capabilities=list(preset_obj.include_capabilities) or None,
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        intents_source = f"preset '{preset}'"
    else:
        # Load saved config from generated mprocs.yaml
        saved_config = load_devenv_config(output_path)

        if saved_config is None:
            click.echo("No dev environment config found.")
            click.echo("Run 'hogli dev:setup' to configure your environment.")
            click.echo("")
            click.echo("Starting with minimal preset for now...")
            saved_config = DevenvConfig(preset="minimal")

        # Build effective config with temporary overrides
        if saved_config.preset:
            preset_obj = resolver.intent_map.presets.get(saved_config.preset)
            if not preset_obj:
                click.echo(f"Warning: Unknown preset '{saved_config.preset}' in config", err=True)
                intents = ["product_analytics"]
                include_caps = None
            elif preset_obj.all_intents:
                intents = list(resolver.intent_map.intents.keys())
                include_caps = list(preset_obj.include_capabilities) or None
            else:
                intents = preset_obj.intents.copy()
                include_caps = list(preset_obj.include_capabilities) or None
        else:
            intents = saved_config.intents.copy()
            include_caps = None

        # Add temporary intents from --with
        intents.extend(with_intents)

        # Merge exclude_units
        exclude_units = list(saved_config.exclude_units) + list(without_units)

        # Build source config (what gets saved)
        source_config = DevenvConfig(
            intents=saved_config.intents if not saved_config.preset else [],
            preset=saved_config.preset,
            include_units=saved_config.include_units,
            exclude_units=saved_config.exclude_units,
            skip_autostart=saved_config.skip_autostart,
        )

        try:
            resolved = resolver.resolve(
                intents,
                include_units=saved_config.include_units,
                exclude_units=exclude_units,
                include_capabilities=include_caps,
                skip_autostart=saved_config.skip_autostart,
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        intents_source = "saved config"

    if explain:
        # Just show what would happen
        click.echo(resolver.explain_resolution(resolved))
        return

    # Generate mprocs config
    registry = create_mprocs_registry()
    generator = MprocsGenerator(registry)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generator.generate_and_save(resolved, output_path, source_config)

    click.echo(f"Generated mprocs config from {intents_source}")
    click.echo(f"  Intents: {', '.join(sorted(resolved.intents))}")
    click.echo(f"  Units: {len(resolved.units)} processes")
    click.echo(f"  Config: {output_path}")
    click.echo("")

    # Start mprocs with the generated config
    repo_root = _get_repo_root()
    mprocs_cmd = ["mprocs", "--config", str(output_path)]

    click.echo("Starting mprocs...")
    os.chdir(repo_root)
    os.execvp("mprocs", mprocs_cmd)


@cli.command(name="dev:explain", help="Show what services would be started for intents")
@click.argument("intents", nargs=-1)
@click.option(
    "--preset",
    help="Explain a preset instead of intents",
)
def dev_explain(intents: tuple[str, ...], preset: str | None) -> None:
    """Show resolution of intents to services.

    If no intents are provided, shows resolution for your current config.
    """
    try:
        resolver = _create_resolver()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in dev/", err=True)
        raise SystemExit(1)

    if preset:
        try:
            resolved = resolver.resolve_preset(preset)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
    elif intents:
        try:
            resolved = resolver.resolve(list(intents))
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)
    else:
        # Use saved config
        output_path = get_generated_mprocs_path()
        saved_config = load_devenv_config(output_path)

        if saved_config is None:
            click.echo("No config found and no intents specified.")
            click.echo("")
            click.echo("Usage:")
            click.echo("  hogli dev:explain error_tracking session_replay")
            click.echo("  hogli dev:explain --preset minimal")
            click.echo("  hogli dev:setup  # to create a config")
            return

        try:
            resolved, _ = _resolve_from_config(resolver, saved_config)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

    click.echo(resolver.explain_resolution(resolved))


@cli.command(name="dev:intents", help="List available intents")
def dev_intents() -> None:
    """List all available intents with descriptions."""
    try:
        resolver = _create_resolver()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found", err=True)
        raise SystemExit(1)

    click.echo("Available intents:")
    click.echo("")

    for name, description in resolver.get_available_intents():
        intent = resolver.intent_map.intents[name]
        click.echo(f"  {name}")
        click.echo(f"    {description}")
        click.echo(f"    Capabilities: {', '.join(intent.capabilities)}")
        click.echo("")


@cli.command(name="dev:presets", help="List available presets")
def dev_presets() -> None:
    """List all available presets with descriptions."""
    try:
        resolver = _create_resolver()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found", err=True)
        raise SystemExit(1)

    click.echo("Available presets:")
    click.echo("")

    for name, description in resolver.get_available_presets():
        preset = resolver.intent_map.presets[name]
        click.echo(f"  {name}")
        click.echo(f"    {description}")
        if preset.all_intents:
            click.echo("    Intents: all")
        else:
            click.echo(f"    Intents: {', '.join(preset.intents)}")
        click.echo("")


@cli.command(name="dev:profile", help="Show current dev environment config")
def dev_profile() -> None:
    """Display the current dev environment configuration."""
    output_path = get_generated_mprocs_path()
    config = load_devenv_config(output_path)

    if config is None:
        click.echo("No dev environment config found.")
        click.echo("")
        click.echo("Run 'hogli dev:setup' to create one.")
        return

    click.echo("Current config:")
    click.echo(f"  Path: {output_path}")
    click.echo("")

    if config.preset:
        click.echo(f"  Preset: {config.preset}")
    elif config.intents:
        click.echo(f"  Intents: {', '.join(config.intents)}")
    else:
        click.echo("  No intents configured")

    if config.include_units:
        click.echo(f"  Include: {', '.join(config.include_units)}")
    if config.exclude_units:
        click.echo(f"  Exclude: {', '.join(config.exclude_units)}")
    if config.skip_autostart:
        click.echo(f"  Manual start: {', '.join(config.skip_autostart)}")


@cli.command(name="dev:setup", help="Interactive wizard to configure your dev environment")
def dev_setup() -> None:
    """Run the interactive setup wizard to configure your development environment."""
    from .wizard import run_setup_wizard

    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in dev/", err=True)
        click.echo("Are you in the PostHog repository root?", err=True)
        raise SystemExit(1)

    run_setup_wizard(intent_map)
