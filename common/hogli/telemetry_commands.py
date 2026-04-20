"""CLI commands for managing hogli telemetry settings."""

from __future__ import annotations

import click
from hogli import telemetry
from hogli.core.cli import cli


@cli.command(name="telemetry:on", help="Enable anonymous usage telemetry")
def telemetry_on() -> None:
    telemetry.set_enabled(True)
    click.echo("Telemetry enabled. Thank you for helping improve hogli!")


@cli.command(name="telemetry:off", help="Disable anonymous usage telemetry")
def telemetry_off() -> None:
    telemetry.set_enabled(False)
    click.echo("Telemetry disabled.")


@cli.command(name="telemetry:status", help="Show current telemetry settings")
def telemetry_status() -> None:
    import os

    enabled = telemetry.is_enabled()
    config_path = telemetry.get_config_path()

    click.echo(f"Telemetry: {'enabled' if enabled else 'disabled'}")

    # Show which mechanism controls the state
    if os.environ.get("CI"):
        click.echo("Controlled by: CI environment detected")
    elif os.environ.get("POSTHOG_TELEMETRY_OPT_OUT") == "1":
        click.echo("Controlled by: POSTHOG_TELEMETRY_OPT_OUT=1")
    elif os.environ.get("DO_NOT_TRACK") == "1":
        click.echo("Controlled by: DO_NOT_TRACK=1")
    else:
        click.echo("Controlled by: config file")

    if enabled:
        click.echo(f"Anonymous ID: {telemetry.get_anonymous_id()}")
    else:
        click.echo("Anonymous ID: (not generated -- telemetry disabled)")
    click.echo(f"Config path: {config_path}")
