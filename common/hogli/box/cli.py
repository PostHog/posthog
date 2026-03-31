"""CLI commands for remote devbox management.

Provides hogli box:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import os
import socket

import click
from hogli.core.cli import cli

from .coder import (
    CLAUDE_OAUTH_PARAMETER,
    create_workspace,
    delete_workspace,
    ensure_coder_authenticated,
    ensure_coder_installed,
    ensure_runtime_ready,
    ensure_tailscale_connected,
    extract_workspace_label,
    get_default_git_identity,
    get_workspace,
    get_workspace_name,
    get_workspace_status,
    list_user_workspaces,
    logs_replace,
    maybe_configure_ssh,
    open_in_browser,
    open_vscode,
    open_web_ide,
    port_forward_replace,
    print_setup_summary,
    replace_with_workspace_command,
    run_in_workspace,
    ssh_replace,
    start_workspace,
    stop_workspace,
    update_workspace_parameters,
)
from .config import load_config, save_git_identity


def resolve_workspace_name(label: str | None, *, for_create: bool = False) -> str:
    """Resolve a workspace name from an optional label.

    When *for_create* is True and no workspaces exist yet, returns the
    default name so the create flow can proceed.
    """
    if label is not None:
        return get_workspace_name(label)

    workspaces = list_user_workspaces()

    if len(workspaces) == 0:
        return get_workspace_name()

    if len(workspaces) == 1:
        return workspaces[0]["name"]

    # Multiple workspaces -- prefer default
    default_name = get_workspace_name()
    for ws in workspaces:
        if ws.get("name") == default_name:
            return default_name

    # No default among multiple -- require explicit --name
    labels = [extract_workspace_label(ws["name"]) or "(default)" for ws in workspaces]
    _fail("Multiple workspaces found. Use --name to pick one:\n" + "".join(f"  {lbl}\n" for lbl in labels))
    return ""  # unreachable


def _fail(message: str) -> None:
    """Print a short actionable error and exit."""
    click.echo(click.style(message, fg="red"))
    raise SystemExit(1)


def _local_port_is_available(port: int) -> bool:
    """Return whether the given localhost TCP port can be bound."""
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                return False
    return True


def workspace_name_option(fn):  # type: ignore[no-untyped-def]
    """Shared Click decorator adding ``--name`` / ``-n`` for workspace selection."""
    return click.option(
        "--name",
        "workspace_label",
        default=None,
        help="Workspace label (omit for default workspace)",
    )(fn)


def _print_connection_info(name: str) -> None:
    """Print connection commands after workspace is ready."""
    label = extract_workspace_label(name)
    suffix = f" --name {label}" if label else ""
    click.echo()
    click.echo(f"  SSH:      hogli box:ssh{suffix}")
    click.echo(f"  Open:     hogli box:open{suffix}")
    click.echo(f"  VS Code:  hogli box:open --vscode{suffix}")
    click.echo(f"  Web IDE:  hogli box:open --web{suffix}")
    click.echo(f"  Claude:   hogli box:claude{suffix}")
    click.echo(f"  Forward:  hogli box:forward{suffix}")
    click.echo(f"  Logs:     hogli box:logs -f{suffix}")
    click.echo(f"  Status:   hogli box:status{suffix}")
    click.echo(f"  Stop:     hogli box:stop{suffix}")


def _maybe_prompt_for_claude_oauth_token(configure_claude: bool | None) -> str | None:
    """Prompt for a Claude token when the user wants workspace auth configured."""
    if token := os.environ.get("HOGLI_BOX_CLAUDE_OAUTH_TOKEN"):
        return token

    if token := os.environ.get("CLAUDE_OAUTH_TOKEN"):
        return token

    if configure_claude is None:
        configure_claude = click.confirm(
            "Configure Claude Code in the workspace?",
            default=True,
        )

    if not configure_claude:
        return None

    click.echo("Run `claude setup-token` in another terminal and paste the token below.")
    token = click.prompt(
        "Claude OAuth token",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    return token or None


def maybe_configure_git_identity(configure_git_identity: bool | None) -> None:
    """Optionally persist Git identity defaults for new workspaces."""
    config = load_config()
    existing_git_name = config.get("git_name")
    existing_git_email = config.get("git_email")
    coder_git_name, coder_git_email = get_default_git_identity()

    default_git_name = existing_git_name or coder_git_name or ""
    default_git_email = existing_git_email or coder_git_email or ""

    if configure_git_identity is None:
        prompt = (
            "Update saved Git identity for new workspaces?"
            if existing_git_name or existing_git_email
            else "Save Git identity for new workspaces?"
        )
        configure_git_identity = click.confirm(
            prompt,
            default=not (existing_git_name or existing_git_email),
        )

    if not configure_git_identity:
        if existing_git_name and existing_git_email:
            click.echo(f"Keeping saved Git identity: {existing_git_name} <{existing_git_email}>")
        elif coder_git_name or coder_git_email:
            click.echo("Skipping saved Git identity setup. New workspaces will use your Coder profile defaults.")
        else:
            click.echo("Skipping saved Git identity setup.")
        return

    git_name = click.prompt(
        "Git name",
        default=default_git_name,
        show_default=bool(default_git_name),
    ).strip()
    git_email = click.prompt(
        "Git email",
        default=default_git_email,
        show_default=bool(default_git_email),
    ).strip()
    if not git_name or not git_email:
        _fail("Git name and Git email are both required when configuring workspace Git identity.")

    save_git_identity(git_name, git_email)
    click.echo(f"Saved Git identity for new workspaces: {git_name} <{git_email}>")


@cli.command(name="box", help="Show available Coder workspace commands")
def box_help() -> None:
    """Show the available `hogli box:*` commands."""
    click.echo("Available workspace commands:")
    click.echo()
    click.echo("  hogli box:setup       install and configure local access")
    click.echo("  hogli box:start       create or start your workspace")
    click.echo("  hogli box:list        list your workspaces")
    click.echo("  hogli box:ssh         open a shell in the workspace")
    click.echo("  hogli box:open        open the workspace in the browser")
    click.echo("  hogli box:claude      verify and launch Claude in the workspace")
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
@click.option(
    "--configure-git-identity/--skip-configure-git-identity",
    default=None,
    help="Prompt for Git name/email defaults for new Coder workspaces",
)
def box_setup(configure_ssh: bool | None, configure_git_identity: bool | None) -> None:
    """Prepare this machine for Coder workspaces."""
    ensure_tailscale_connected("rerun `hogli box:setup`.")
    ensure_coder_installed()
    ensure_coder_authenticated()
    maybe_configure_ssh(configure_ssh=configure_ssh)
    maybe_configure_git_identity(configure_git_identity)
    print_setup_summary()


@cli.command(name="box:list", help="List your devboxes")
def box_list() -> None:
    """List all workspaces belonging to the current user."""
    ensure_runtime_ready()
    workspaces = list_user_workspaces()

    if not workspaces:
        click.echo("No devboxes found. Run 'hogli box:start' to create one.")
        return

    click.echo(f"{'LABEL':<16} {'STATUS':<12} {'NAME'}")
    for ws in workspaces:
        ws_name = ws.get("name", "")
        label = extract_workspace_label(ws_name) or "(default)"
        status = get_workspace_status(ws)
        color = {
            "running": "green",
            "stopped": "yellow",
            "starting": "cyan",
            "stopping": "yellow",
            "failed": "red",
            "deleting": "red",
        }.get(status, "white")
        click.echo(f"  {label:<14} {click.style(status, fg=color):<20} {ws_name}")


@cli.command(name="box:start", help="Start or create your remote devbox")
@workspace_name_option
@click.option(
    "--disk",
    type=click.Choice(["30", "50", "100"]),
    default="50",
    help="Disk size in GiB (default: 50)",
)
@click.option(
    "--configure-claude/--skip-configure-claude",
    default=None,
    help="Prompt for a Claude OAuth token when creating a new workspace",
)
@click.option(
    "--claude-oauth-token",
    envvar="HOGLI_BOX_CLAUDE_OAUTH_TOKEN",
    hidden=True,
)
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def box_start(
    workspace_label: str | None,
    disk: str,
    configure_claude: bool | None,
    claude_oauth_token: str | None,
    verbose: bool,
) -> None:
    """Start or create the remote devbox."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label, for_create=True)
    ws = get_workspace(name)

    if ws is not None:
        status = get_workspace_status(ws)
        if status == "running":
            click.echo(f"Devbox '{name}' is already running.")
            _print_connection_info(name)
            return

        if status == "stopped":
            click.echo(f"Starting devbox '{name}'...")
            start_workspace(name, verbose=verbose)
            click.echo("Started.")
            _print_connection_info(name)
            return

        click.echo(f"Devbox '{name}' is in state: {status}")
        if status in ("starting", "stopping", "deleting"):
            click.echo("Wait for the current operation to complete.")
            return

        click.echo("Attempting to start...")
        start_workspace(name, verbose=verbose)
        _print_connection_info(name)
        return

    token = claude_oauth_token or _maybe_prompt_for_claude_oauth_token(configure_claude)
    config = load_config()

    click.echo(f"Creating devbox '{name}' (disk={disk}GiB)...")
    create_workspace(
        name,
        int(disk),
        claude_oauth_token=token,
        git_name=config.get("git_name"),
        git_email=config.get("git_email"),
        verbose=verbose,
    )
    click.echo("Created.")
    click.echo()
    click.echo(
        f"  SSH:   hogli box:ssh{' --name ' + extract_workspace_label(name) if extract_workspace_label(name) else ''}"
    )
    click.echo()
    click.echo("  Run `hogli box --help` for more commands.")


@cli.command(name="box:stop", help="Stop your devbox (preserves disk, stops billing)")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def box_stop(workspace_label: str | None, verbose: bool) -> None:
    """Stop the devbox. State is preserved on the EBS volume."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found. Run 'hogli box:start' to create one.")
        raise SystemExit(1)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name, verbose=verbose)
    click.echo("Stopped. Disk preserved. Run 'hogli box:start' to resume.")


@cli.command(name="box:ssh", help="SSH into your devbox")
@workspace_name_option
def box_ssh(workspace_label: str | None) -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    ssh_replace(name)


@cli.command(name="box:open", help="Open devbox in browser or VS Code")
@workspace_name_option
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def box_open(workspace_label: str | None, vscode: bool, web: bool) -> None:
    """Open the devbox in a browser or editor."""
    if vscode and web:
        raise click.UsageError("Choose either `--vscode` or `--web`.")

    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)

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
@workspace_name_option
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def box_logs(workspace_label: str | None, follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    logs_replace(name, follow)


@cli.command(name="box:claude", help="Verify and launch Claude Code in your devbox")
@workspace_name_option
@click.option("--check", is_flag=True, help="Check Claude readiness without launching it")
@click.option("--set-token", is_flag=True, help="Prompt for a Claude OAuth token and sync it to the workspace")
@click.option(
    "--claude-oauth-token",
    envvar="HOGLI_BOX_CLAUDE_OAUTH_TOKEN",
    hidden=True,
)
def box_claude(workspace_label: str | None, check: bool, set_token: bool, claude_oauth_token: str | None) -> None:
    """Sync Claude auth into the workspace or launch Claude there."""
    if check and set_token:
        raise click.UsageError("Choose either `--check` or `--set-token`.")

    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    workspace = get_workspace(name)

    if workspace is None:
        click.echo("No devbox found. Run 'hogli box:start' to create one.")
        raise SystemExit(1)

    status = get_workspace_status(workspace)
    if status != "running":
        click.echo(f"Devbox '{name}' is not running. Run 'hogli box:start' first.")
        raise SystemExit(1)

    if set_token:
        token = claude_oauth_token or _maybe_prompt_for_claude_oauth_token(True)
        if not token:
            click.echo("No Claude OAuth token provided.")
            raise SystemExit(1)

        click.echo("Syncing Claude OAuth token to the workspace...")
        click.echo("Coder may reprovision the workspace if the template requires it.")
        update_workspace_parameters(name, {CLAUDE_OAUTH_PARAMETER: token})
        click.echo("Claude OAuth token synced.")
        return

    check_result = run_in_workspace(
        name,
        [
            "sh",
            "-lc",
            "command -v claude >/dev/null && claude auth status >/dev/null 2>&1",
        ],
        capture_output=True,
    )
    if check_result.returncode != 0:
        click.echo("Claude Code is not ready in the workspace.")
        click.echo("Run `hogli box:claude --set-token` to sync your Claude OAuth token.")
        raise SystemExit(1)

    if check:
        click.echo("Claude Code is ready in the workspace.")
        return

    click.echo(f"Launching Claude Code in '{name}'...")
    replace_with_workspace_command(name, ["claude"])


@cli.command(name="box:destroy", help="Destroy your devbox and its data")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def box_destroy(workspace_label: str | None, verbose: bool) -> None:
    """Destroy the devbox completely."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found.")
        return

    if not click.confirm(f"Destroy '{name}'? This deletes the VM and its data"):
        click.echo("Cancelled.")
        return

    delete_workspace(name, verbose=verbose)
    click.echo("Destroyed.")


@cli.command(name="box:status", help="Show devbox status")
@workspace_name_option
def box_status(workspace_label: str | None) -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)

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
@workspace_name_option
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def box_forward(workspace_label: str | None, port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    if not _local_port_is_available(port):
        _fail(
            f"Local port {port} is already in use.\n"
            f"Stop the process using that port or rerun with `hogli box:forward --port {port + 1}`."
        )

    click.echo(f"Forwarding {name}:8010 -> localhost:{port}")
    click.echo(f"PostHog UI at http://localhost:{port}")
    click.echo("Ctrl+C to stop")
    click.echo()
    port_forward_replace(name, port, 8010)
