"""Interactive wizard for developer environment setup.

Provides a user-friendly interface for selecting intents and configuring
the development profile.
"""

from __future__ import annotations

import click

from .profile import DeveloperProfile, ProfileManager, ProfileOverrides
from .resolver import IntentMap, IntentResolver


class SetupWizard:
    """Interactive wizard for setting up developer profile."""

    def __init__(
        self,
        intent_map: IntentMap,
        manager: ProfileManager,
    ):
        self.intent_map = intent_map
        self.manager = manager
        self.resolver = IntentResolver(intent_map)

    def run(self) -> DeveloperProfile | None:
        """Run the interactive setup wizard.

        Returns:
            The created profile, or None if cancelled
        """
        click.echo("")
        click.echo(click.style("PostHog Developer Environment Setup", fg="green", bold=True))
        click.echo("")
        click.echo("This wizard helps you configure which services to start based on")
        click.echo("the products you're working on.")
        click.echo("")

        # Check for existing profile
        existing = self.manager.load_profile()
        if existing:
            click.echo("You have an existing profile:")
            click.echo(self.manager.get_profile_summary(existing))
            click.echo("")
            if not click.confirm("Replace it with a new configuration?", default=True):
                return None

        # Ask whether to use preset or custom selection
        click.echo("")
        choice = self._prompt_setup_type()

        if choice == "preset":
            profile = self._setup_from_preset()
        else:
            profile = self._setup_from_intents()

        if profile is None:
            return None

        # Ask about overrides
        profile = self._configure_overrides(profile)

        # Show summary and confirm
        click.echo("")
        click.echo(click.style("Configuration Summary", fg="cyan", bold=True))
        click.echo("-" * 40)
        click.echo(self.manager.get_profile_summary(profile))
        click.echo("")

        # Show what would be started
        if profile.preset:
            resolved = self.resolver.resolve_preset(profile.preset)
        else:
            resolved = self.resolver.resolve(
                profile.intents,
                include_units=profile.overrides.include_units,
                exclude_units=profile.overrides.exclude_units,
            )
        click.echo(f"This will start {len(resolved.units)} processes:")
        click.echo(f"  {', '.join(sorted(resolved.units))}")
        click.echo("")

        if not click.confirm("Save this configuration?", default=True):
            click.echo("Configuration cancelled.")
            return None

        # Save profile
        self.manager.save_profile(profile)
        click.echo("")
        click.echo(click.style("✓ Profile saved!", fg="green"))
        click.echo(f"  Location: {self.manager.profile_path}")
        click.echo("")
        click.echo("Run 'hogli dev:start' to start your development environment.")

        return profile

    def _prompt_setup_type(self) -> str:
        """Prompt user to choose setup type."""
        click.echo("How would you like to configure your environment?")
        click.echo("")
        click.echo("  1. Use a preset (recommended for most developers)")
        click.echo("  2. Select specific products (advanced)")
        click.echo("")

        choice = click.prompt(
            "Enter choice",
            type=click.Choice(["1", "2"]),
            default="1",
        )

        return "preset" if choice == "1" else "custom"

    def _setup_from_preset(self) -> DeveloperProfile | None:
        """Set up profile using a preset."""
        click.echo("")
        click.echo(click.style("Available Presets", fg="cyan"))
        click.echo("")

        presets = list(self.intent_map.presets.items())
        for i, (name, preset) in enumerate(presets, 1):
            intents_str = "all" if preset.all_intents else ", ".join(preset.intents)
            click.echo(f"  {i}. {name}")
            click.echo(f"     {preset.description}")
            click.echo(f"     Intents: {intents_str}")
            click.echo("")

        choices = [str(i) for i in range(1, len(presets) + 1)]
        choice = click.prompt(
            "Select preset",
            type=click.Choice(choices),
            default="1",
        )

        selected_name = presets[int(choice) - 1][0]
        return DeveloperProfile(preset=selected_name)

    def _setup_from_intents(self) -> DeveloperProfile:
        """Set up profile by selecting specific intents."""
        click.echo("")
        click.echo(click.style("Available Products/Features", fg="cyan"))
        click.echo("Select the products you'll be working on (comma-separated numbers).")
        click.echo("")

        intents = list(self.intent_map.intents.items())
        for i, (name, intent) in enumerate(intents, 1):
            click.echo(f"  {i:2}. {name}")
            click.echo(f"      {intent.description}")

        click.echo("")

        # Get selections
        selection = click.prompt(
            "Enter numbers (e.g., 1,3,5)",
            default="1",
        )

        # Parse selection
        selected_intents = []
        try:
            indices = [int(x.strip()) for x in selection.split(",")]
            for idx in indices:
                if 1 <= idx <= len(intents):
                    selected_intents.append(intents[idx - 1][0])
        except ValueError:
            click.echo("Invalid selection, using product_analytics as default.")
            selected_intents = ["product_analytics"]

        if not selected_intents:
            selected_intents = ["product_analytics"]

        return DeveloperProfile(intents=selected_intents)

    def _configure_overrides(self, profile: DeveloperProfile) -> DeveloperProfile:
        """Optionally configure overrides."""
        click.echo("")
        if not click.confirm("Configure additional options?", default=False):
            return profile

        overrides = ProfileOverrides()

        # Include units
        click.echo("")
        click.echo("Additional units to always include (e.g., storybook):")
        include = click.prompt("Enter unit names (comma-separated, or blank)", default="")
        if include.strip():
            overrides.include_units = [u.strip() for u in include.split(",") if u.strip()]

        # Exclude units
        click.echo("")
        click.echo("Units to always exclude (e.g., dagster):")
        exclude = click.prompt("Enter unit names (comma-separated, or blank)", default="")
        if exclude.strip():
            overrides.exclude_units = [u.strip() for u in exclude.split(",") if u.strip()]

        # Skip typegen
        click.echo("")
        overrides.skip_typegen = click.confirm("Skip typegen?", default=False)

        profile.overrides = overrides
        return profile


def run_setup_wizard(
    intent_map: IntentMap,
    manager: ProfileManager | None = None,
) -> DeveloperProfile | None:
    """Run the setup wizard.

    Args:
        intent_map: The intent map
        manager: Profile manager, or None to use default

    Returns:
        The created profile, or None if cancelled
    """
    if manager is None:
        manager = ProfileManager()

    wizard = SetupWizard(intent_map, manager)
    return wizard.run()
