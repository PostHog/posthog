"""CLI commands for remote devbox management.

Provides hogli box:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import click
from hogli.core.cli import cli

from .coder import (
    create_workspace,
    delete_workspace,
    ensure_coder_authenticated,
    ensure_coder_installed,
    ensure_runtime_ready,
    ensure_tailscale_connected,
    get_workspace,
    get_workspace_name,
    get_workspace_status,
    logs_replace,
    maybe_configure_ssh,
    open_in_browser,
    open_vscode,
    open_web_ide,
    port_forward_replace,
    print_setup_summary,
    ssh_replace,
    start_workspace,
    stop_workspace,
)


def _print_connection_info(name: str) -> None:
    """Print connection commands after workspace is ready."""
    click.echo()
    click.echo("  SSH:      hogli box:ssh")
    click.echo("  Open:     hogli box:open")
    click.echo("  VS Code:  hogli box:open --vscode")
    click.echo("  Web IDE:  hogli box:open --web")
    click.echo("  Forward:  hogli box:forward")
    click.echo("  Logs:     hogli box:logs -f")
    click.echo("  Status:   hogli box:status")
    click.echo("  Stop:     hogli box:stop")


@cli.command(name="box", help="Show available Coder workspace commands")
def box_help() -> None:
    """Show the available `hogli box:*` commands."""
    click.echo("Available workspace commands:")
    click.echo()
    click.echo("  hogli box:setup       install and configure local access")
    click.echo("  hogli box:start       create or start your workspace")
    click.echo("  hogli box:ssh         open a shell in the workspace")
    click.echo("  hogli box:open        open the workspace in the browser")
    click.echo("  hogli box:forward     forward the PostHog UI to localhost")
    click.echo("  hogli box:logs        stream workspace logs")
    click.echo("  hogli box:status      show current workspace status")
    click.echo("  hogli box:stop        stop the workspace")
    click.echo("  hogli box:destroy     delete the workspace and its data")
    click.echo()
    click.echo("Run `hogli <command> --help` for command-specific options.")


@cli.command(name="box:setup", help="Install and configure local access to Coder devboxes")
@click.option(
    "--configure-ssh/--skip-configure-ssh",
    default=None,
    help="Configure local SSH host entries for Coder workspaces during setup",
)
def box_setup(configure_ssh: bool | None) -> None:
    """Prepare this machine for Coder workspaces."""
    ensure_tailscale_connected("rerun `hogli box:setup`.")
    ensure_coder_installed()
    ensure_coder_authenticated()
    maybe_configure_ssh(configure_ssh=configure_ssh)
    print_setup_summary()


@cli.command(name="box:start", help="Start or create your remote devbox")
@click.option(
    "--disk",
    type=click.Choice(["30", "50", "100"]),
    default="50",
    help="Disk size in GiB (default: 50)",
)
@click.option("--branch", default="master", help="Git branch to check out on the devbox")
def box_start(disk: str, branch: str) -> None:
    """Start or create the remote devbox."""
    ensure_runtime_ready()
    name = get_workspace_name()
    ws = get_workspace(name)

    if ws is not None:
        status = get_workspace_status(ws)
        if status == "running":
            click.echo(f"Devbox '{name}' is already running.")
            _print_connection_info(name)
            return

        if status == "stopped":
            click.echo(f"Starting devbox '{name}'...")
            start_workspace(name)
            click.echo("Started.")
            _print_connection_info(name)
            return

        click.echo(f"Devbox '{name}' is in state: {status}")
        if status in ("starting", "stopping", "deleting"):
            click.echo("Wait for the current operation to complete.")
            return

        click.echo("Attempting to start...")
        start_workspace(name)
        _print_connection_info(name)
        return

    click.echo(f"Creating devbox '{name}' (disk={disk}GiB, branch={branch})...")
    create_workspace(name, int(disk), branch)
    click.echo("Created.")
    _print_connection_info(name)


@cli.command(name="box:stop", help="Stop your devbox (preserves disk, stops billing)")
def box_stop() -> None:
    """Stop the devbox. State is preserved on the EBS volume."""
    ensure_runtime_ready()
    name = get_workspace_name()

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found. Run 'hogli box:start' to create one.")
        raise SystemExit(1)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name)
    click.echo("Stopped. Disk preserved. Run 'hogli box:start' to resume.")


@cli.command(name="box:ssh", help="SSH into your devbox")
def box_ssh() -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name = get_workspace_name()
    ssh_replace(name)


@cli.command(name="box:open", help="Open devbox in browser or VS Code")
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def box_open(vscode: bool, web: bool) -> None:
    """Open the devbox in a browser or editor."""
    if vscode and web:
        raise click.UsageError("Choose either `--vscode` or `--web`.")

    ensure_runtime_ready()
    name = get_workspace_name()

    if vscode:
        click.echo(f"Opening '{name}' in VS Code...")
        open_vscode(name)
    elif web:
        click.echo(f"Opening code-server for '{name}'...")
        open_web_ide(name)
    else:
        click.echo(f"Opening '{name}' in browser...")
        open_in_browser(name)


@cli.command(name="box:logs", help="Tail devbox build and agent logs")
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def box_logs(follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name = get_workspace_name()
    logs_replace(name, follow)


@cli.command(name="box:destroy", help="Destroy your devbox and its data")
def box_destroy() -> None:
    """Destroy the devbox completely."""
    ensure_runtime_ready()
    name = get_workspace_name()

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found.")
        return

    if not click.confirm(f"Destroy '{name}'? This deletes the VM and its data"):
        click.echo("Cancelled.")
        return

    delete_workspace(name)
    click.echo("Destroyed.")


@cli.command(name="box:status", help="Show devbox status")
def box_status() -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name = get_workspace_name()

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found. Run 'hogli box:start' to create one.")
        return

    status = get_workspace_status(ws)
    color = {
        "running": "green",
        "stopped": "yellow",
        "starting": "cyan",
        "stopping": "yellow",
        "failed": "red",
        "deleting": "red",
    }.get(status, "white")

    click.echo(f"  Name:    {name}")
    click.echo(f"  Status:  {click.style(status, fg=color)}")

    if ws.get("outdated"):
        click.echo(click.style("  Update:  template update available", fg="yellow"))
        click.echo("           Recreate the workspace when you want the latest template.")

    # Show agent status if available
    resources = ws.get("latest_build", {}).get("resources", [])
    for resource in resources:
        for agent in resource.get("agents", []):
            agent_status = agent.get("status", "unknown")
            click.echo(f"  Agent:   {agent_status}")

    if status == "running":
        _print_connection_info(name)


@cli.command(name="box:forward", help="Forward PostHog UI to localhost")
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def box_forward(port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name = get_workspace_name()

    click.echo(f"Forwarding {name}:8010 -> localhost:{port}")
    click.echo(f"PostHog UI at http://localhost:{port}")
    click.echo("Ctrl+C to stop")
    click.echo()
    port_forward_replace(name, port, 8010)
