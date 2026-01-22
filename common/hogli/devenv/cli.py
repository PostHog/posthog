"""CLI commands for intent-based developer environment.

Provides hogli dev:* commands for managing the development environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
from hogli.core.cli import cli

from .generator import create_generator
from .profile import DeveloperProfile, ProfileManager
from .resolver import IntentResolver, load_intent_map


def _get_repo_root() -> Path:
    """Get repository root path."""
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def _ensure_profile_or_prompt(manager: ProfileManager) -> DeveloperProfile:
    """Ensure a profile exists, prompting to create one if not.

    Returns:
        The developer profile
    """
    profile = manager.load_profile()

    if profile is None:
        click.echo("No developer profile found.")
        click.echo("Run 'hogli dev:setup' to configure your environment.")
        click.echo("")
        click.echo("Starting with minimal preset for now...")
        profile = manager.create_preset_profile("minimal")

    return profile


@cli.command(name="dev:start", help="Start dev environment based on your profile")
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
    help="Temporarily exclude unit(s) from this run",
)
@click.option(
    "--preset",
    help="Use a preset instead of profile (minimal, backend, replay, ai, full)",
)
@click.option(
    "--explain",
    is_flag=True,
    help="Show what would be started without actually starting",
)
@click.option(
    "--skip-typegen",
    is_flag=True,
    help="Skip typegen process",
)
def dev_start(
    with_intents: tuple[str, ...],
    without_units: tuple[str, ...],
    preset: str | None,
    explain: bool,
    skip_typegen: bool,
) -> None:
    """Start development environment based on your profile.

    Uses your saved profile from .posthog/dev.yaml or prompts to create one.
    Generated mprocs configuration is saved to .posthog/.generated/mprocs.yaml.
    """
    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in dev/", err=True)
        click.echo("Are you in the PostHog repository root?", err=True)
        raise SystemExit(1)

    resolver = IntentResolver(intent_map)
    manager = ProfileManager()

    # Track effective skip_typegen
    effective_skip_typegen = skip_typegen

    # Determine intents to use
    if preset:
        # Use preset directly
        try:
            resolved = resolver.resolve_preset(
                preset,
                include_units=list(with_intents),
                exclude_units=list(without_units),
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        intents_source = f"preset '{preset}'"
    else:
        # Load profile
        profile = _ensure_profile_or_prompt(manager)

        # Merge profile intents with temporary additions
        if profile.preset:
            # Profile uses a preset
            try:
                preset_obj = intent_map.presets[profile.preset]
                if preset_obj.all_intents:
                    intents = list(intent_map.intents.keys())
                else:
                    intents = preset_obj.intents.copy()
            except KeyError:
                click.echo(f"Warning: Unknown preset '{profile.preset}' in profile", err=True)
                intents = ["product_analytics"]
        else:
            intents = profile.intents.copy()

        # Add temporary intents
        intents.extend(with_intents)

        # Merge overrides
        include_units = list(profile.overrides.include_units)
        exclude_units = list(profile.overrides.exclude_units) + list(without_units)

        # Apply skip_typegen from profile or flag
        effective_skip_typegen = skip_typegen or profile.overrides.skip_typegen

        try:
            resolved = resolver.resolve(
                intents,
                include_units=include_units,
                exclude_units=exclude_units,
            )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise SystemExit(1)

        intents_source = "profile"

    if explain:
        # Just show what would happen
        click.echo(resolver.explain_resolution(resolved))
        return

    # Generate mprocs config
    generator = create_generator()
    output_path = manager.get_generated_mprocs_path()
    manager.ensure_generated_dir()

    generator.generate_and_save(resolved, output_path, skip_typegen=effective_skip_typegen)

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

    If no intents are provided, shows resolution for your current profile.
    """
    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in dev/", err=True)
        raise SystemExit(1)

    resolver = IntentResolver(intent_map)

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
        # Use profile
        manager = ProfileManager()
        profile = manager.load_profile()

        if profile is None:
            click.echo("No profile found and no intents specified.")
            click.echo("")
            click.echo("Usage:")
            click.echo("  hogli dev:explain error_tracking session_replay")
            click.echo("  hogli dev:explain --preset minimal")
            click.echo("  hogli dev:setup  # to create a profile")
            return

        if profile.preset:
            resolved = resolver.resolve_preset(profile.preset)
        else:
            resolved = resolver.resolve(
                profile.intents,
                include_units=profile.overrides.include_units,
                exclude_units=profile.overrides.exclude_units,
            )

    click.echo(resolver.explain_resolution(resolved))


@cli.command(name="dev:intents", help="List available intents")
def dev_intents() -> None:
    """List all available intents with descriptions."""
    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found", err=True)
        raise SystemExit(1)

    click.echo("Available intents:")
    click.echo("")

    for name, intent in sorted(intent_map.intents.items()):
        click.echo(f"  {name}")
        click.echo(f"    {intent.description}")
        click.echo(f"    Capabilities: {', '.join(intent.capabilities)}")
        click.echo("")


@cli.command(name="dev:presets", help="List available presets")
def dev_presets() -> None:
    """List all available presets with descriptions."""
    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found", err=True)
        raise SystemExit(1)

    click.echo("Available presets:")
    click.echo("")

    for name, preset in sorted(intent_map.presets.items()):
        click.echo(f"  {name}")
        click.echo(f"    {preset.description}")
        if preset.all_intents:
            click.echo("    Intents: all")
        else:
            click.echo(f"    Intents: {', '.join(preset.intents)}")
        click.echo("")


@cli.command(name="dev:profile", help="Show current developer profile")
def dev_profile() -> None:
    """Display the current developer profile."""
    manager = ProfileManager()
    profile = manager.load_profile()

    if profile is None:
        click.echo("No developer profile found.")
        click.echo("")
        click.echo("Run 'hogli dev:setup' to create one.")
        return

    click.echo("Current profile:")
    click.echo(f"  Path: {manager.profile_path}")
    click.echo("")
    click.echo(manager.get_profile_summary(profile))


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

    manager = ProfileManager()
    run_setup_wizard(intent_map, manager)


@cli.command(name="dev:edit", help="Re-run setup wizard to edit your profile")
def dev_edit() -> None:
    """Re-run the setup wizard to modify your existing profile."""
    from .wizard import run_setup_wizard

    try:
        intent_map = load_intent_map()
    except FileNotFoundError:
        click.echo("Error: intent-map.yaml not found in dev/", err=True)
        raise SystemExit(1)

    manager = ProfileManager()
    run_setup_wizard(intent_map, manager)
