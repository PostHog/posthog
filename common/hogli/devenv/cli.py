"""CLI commands for intent-based developer environment.

Provides hogli dev:* commands for managing the development environment.
"""

from __future__ import annotations

import click
from hogli.core.cli import cli

from .generator import DevenvConfig, MprocsGenerator, get_generated_mprocs_path, load_devenv_config
from .registry import create_mprocs_registry
from .resolver import IntentResolver, load_intent_map


def _create_resolver() -> IntentResolver:
    """Create an IntentResolver with the default intent map and mprocs registry."""
    intent_map = load_intent_map()
    registry = create_mprocs_registry()
    return IntentResolver(intent_map, registry)


@cli.command(name="dev:generate", help="Regenerate mprocs config from saved settings")
@click.option(
    "--with",
    "with_intents",
    multiple=True,
    help="Temporarily add intent(s) for this generation",
)
@click.option(
    "--without",
    "without_units",
    multiple=True,
    help="Temporarily exclude unit(s) for this generation (e.g., --without typegen)",
)
def dev_generate(
    with_intents: tuple[str, ...],
    without_units: tuple[str, ...],
) -> None:
    """Regenerate mprocs config from saved settings.

    Picks up changes from intent-map.yaml without starting mprocs.
    Run 'hogli start' to start the dev environment.
    """
    try:
        resolver = _create_resolver()
    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Are you in the PostHog repository root?", err=True)
        raise SystemExit(1)

    output_path = get_generated_mprocs_path()

    # Load saved config
    saved_config = load_devenv_config(output_path)

    if saved_config is None:
        click.echo("No dev environment config found.")
        click.echo("Run 'hogli dev:setup' to configure your environment.")
        click.echo("")
        click.echo("Using default intents for now...")
        saved_config = DevenvConfig(intents=["product_analytics"])

    # Build effective intents with temporary overrides
    intents = saved_config.intents.copy()
    intents.extend(with_intents)

    # Merge exclude_units
    exclude_units = list(saved_config.exclude_units) + list(without_units)

    try:
        resolved = resolver.resolve(
            intents,
            include_units=saved_config.include_units,
            exclude_units=exclude_units,
            skip_autostart=saved_config.skip_autostart,
            enable_autostart=saved_config.enable_autostart,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)

    # Generate mprocs config
    registry = create_mprocs_registry()
    generator = MprocsGenerator(registry)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    generator.generate_and_save(resolved, output_path, saved_config)

    click.echo("Generated mprocs config from saved config")
    click.echo(f"  Products: {', '.join(sorted(resolved.intents))}")
    click.echo(f"  Units: {len(resolved.units)} processes")
    click.echo(f"  Config: {output_path}")
    click.echo("")
    click.echo("Run 'hogli dev:setup' to change your environment.")


@cli.command(name="dev:explain", help="Show what services would be started for intents")
@click.argument("intents", nargs=-1)
def dev_explain(intents: tuple[str, ...]) -> None:
    """Show resolution of intents to services.

    If no intents are provided, shows resolution for your current config.
    """
    try:
        resolver = _create_resolver()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in devenv/", err=True)
        raise SystemExit(1)

    if intents:
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
            click.echo("  hogli dev:setup  # to create a config")
            return

        try:
            resolved = resolver.resolve(
                saved_config.intents,
                include_units=saved_config.include_units,
                exclude_units=saved_config.exclude_units,
                skip_autostart=saved_config.skip_autostart,
                enable_autostart=saved_config.enable_autostart,
            )
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


@cli.command(name="dev:setup", help="Interactive wizard to configure your dev environment")
@click.option("--log", "log_to_files", is_flag=True, help="Log process output to /tmp/posthog-*.log files")
def dev_setup(log_to_files: bool) -> None:
    """Run the interactive setup wizard to configure your development environment."""
    from .wizard import run_setup_wizard

    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in devenv/", err=True)
        click.echo("Are you in the PostHog repository root?", err=True)
        raise SystemExit(1)

    run_setup_wizard(intent_map, log_to_files=log_to_files)
