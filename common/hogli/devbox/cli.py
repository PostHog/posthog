"""CLI commands for remote devbox management.

Provides hogli devbox:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import os
import errno
import socket
from collections.abc import Callable
from typing import Any

import click
from hogli.core.cli import cli

from . import keychain
from .coder import (
    DOTFILES_URI_PARAMETER,
    GIT_EMAIL_PARAMETER,
    GIT_NAME_PARAMETER,
    _fail,
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
    open_cursor,
    open_in_browser,
    open_vscode,
    open_web_ide,
    port_forward_replace,
    print_setup_summary,
    restart_workspace,
    ssh_replace,
    start_workspace,
    stop_workspace,
    update_workspace,
    update_workspace_parameters,
)
from .config import load_config, save_dotfiles_uri, save_git_identity

_CLAUDE_TOKEN_SERVICE = "posthog-claude-oauth-token"

WORKSPACE_STATUS_COLORS = {
    "running": "green",
    "stopped": "yellow",
    "starting": "cyan",
    "stopping": "yellow",
    "failed": "red",
    "deleting": "red",
}
PENDING_WORKSPACE_STATES = {"starting", "stopping", "deleting"}


def resolve_workspace_name(label: str | None) -> tuple[str, list[dict[str, Any]]]:
    """Resolve a workspace name from an optional label.

    Returns (name, workspaces) where workspaces is the already-fetched list
    when available, so callers can skip a second ``_list_workspaces`` call.
    """
    if label is not None:
        return get_workspace_name(label), []

    workspaces = list_user_workspaces()

    if len(workspaces) == 0:
        return get_workspace_name(), workspaces

    if len(workspaces) == 1:
        return workspaces[0]["name"], workspaces

    # Multiple workspaces -- prefer default
    default_name = get_workspace_name()
    for ws in workspaces:
        if ws.get("name") == default_name:
            return default_name, workspaces

    # No default among multiple -- require explicit --name
    labels = [extract_workspace_label(ws["name"]) or "(default)" for ws in workspaces]
    _fail("Multiple workspaces found. Use --name to pick one:\n" + "".join(f"  {lbl}\n" for lbl in labels))


def _local_port_is_available(port: int) -> bool:
    """Return whether the given localhost TCP port can be bound."""
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
        except OSError as err:
            if err.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            return False
    return True


def workspace_name_option(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Shared Click decorator adding ``--name`` / ``-n`` for workspace selection."""
    return click.option(
        "--name",
        "workspace_label",
        default=None,
        help="Workspace label (omit for default workspace)",
    )(fn)


def _print_connection_info(name: str) -> None:
    """Print connection commands after workspace is ready."""
    suffix = _workspace_label_suffix(name)
    commands = [
        ("SSH", "devbox:ssh"),
        ("Open", "devbox:open"),
        ("VS Code", "devbox:open --vscode"),
        ("Cursor", "devbox:open --cursor"),
        ("Web IDE", "devbox:open --web"),
        ("Forward", "devbox:forward"),
        ("Logs", "devbox:logs -f"),
        ("Status", "devbox:status"),
        ("Stop", "devbox:stop"),
    ]

    click.echo()
    for label, command in commands:
        click.echo(f"  {label:<8} hogli {command}{suffix}")


def _workspace_label_suffix(name: str) -> str:
    """Return the optional CLI suffix for a named workspace."""
    label = extract_workspace_label(name)
    return f" --name {label}" if label else ""


def _get_workspace_or_fail(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a workspace or exit with a consistent message when missing."""
    workspace = get_workspace(name, workspaces or None)
    if workspace is not None:
        return workspace
    _fail("No devbox found. Run 'hogli devbox:start' to create one.")


def _workspace_status_color(status: str) -> str:
    """Return the display color for a workspace status."""
    return WORKSPACE_STATUS_COLORS.get(status, "white")


def _sync_workspace_parameters(name: str) -> None:
    """Push local config (git identity, dotfiles) to workspace parameters before start."""
    config = load_config()
    params: dict[str, str] = {}

    git_name = config.get("git_name")
    git_email = config.get("git_email")
    if git_name and git_email:
        params[GIT_NAME_PARAMETER] = git_name
        params[GIT_EMAIL_PARAMETER] = git_email

    dotfiles_uri = config.get("dotfiles_uri")
    if dotfiles_uri:
        params[DOTFILES_URI_PARAMETER] = dotfiles_uri

    if params:
        update_workspace_parameters(name, params)


def _start_existing_workspace(name: str, workspace: dict[str, Any], *, verbose: bool) -> None:
    """Handle `devbox:start` when the workspace already exists."""
    status = get_workspace_status(workspace)
    if status == "running":
        click.echo(f"Devbox '{name}' is already running.")
        _print_connection_info(name)
        return

    if status in PENDING_WORKSPACE_STATES:
        click.echo(f"Devbox '{name}' is in state: {status}")
        click.echo("Wait for the current operation to complete.")
        return

    _sync_workspace_parameters(name)

    if status == "stopped":
        click.echo(f"Starting devbox '{name}'...")
        start_workspace(name, verbose=verbose)
        click.echo("Started.")
        _print_connection_info(name)
        return

    click.echo(f"Devbox '{name}' is in state: {status}")
    click.echo("Attempting to start...")
    start_workspace(name, verbose=verbose)
    _print_connection_info(name)


def _prompt_for_claude_token() -> str | None:
    """Prompt for a Claude OAuth token and save it to Keychain."""
    click.echo("Run `claude setup-token` in another terminal to generate a token.")
    click.pause("Press Enter when you have the token ready...")
    token = click.prompt(
        "Claude OAuth token",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    if not token:
        return None

    if keychain.write(_CLAUDE_TOKEN_SERVICE, token):
        click.echo("Saved to Keychain for future workspaces.")
    return token


def _maybe_prompt_for_claude_oauth_token(configure_claude: bool | None) -> str | None:
    """Resolve a Claude OAuth token from env, Keychain, or interactive prompt.

    When configure_claude is True (explicit --configure-claude), the user is
    asked for a fresh token even if one exists in Keychain. This lets users
    replace an expired token without a separate ``devbox:auth --set`` call.
    """
    if token := os.environ.get("CLAUDE_OAUTH_TOKEN"):
        return token

    # Explicit --configure-claude: skip cached token, prompt for a fresh one
    if configure_claude is True:
        return _prompt_for_claude_token()

    if token := keychain.read(_CLAUDE_TOKEN_SERVICE):
        click.echo("Using Claude token from Keychain. Pass --configure-claude to replace it.")
        return token

    if configure_claude is None:
        configure_claude = click.confirm(
            "Configure Claude Code in the workspace?",
            default=True,
        )

    if not configure_claude:
        return None

    return _prompt_for_claude_token()


def maybe_configure_git_identity(configure_git_identity: bool | None) -> None:
    """Optionally persist Git identity defaults for new workspaces."""
    config = load_config()
    existing_git_name = config.get("git_name")
    existing_git_email = config.get("git_email")

    if configure_git_identity is False:
        if existing_git_name and existing_git_email:
            click.echo(f"Using saved Git identity: {existing_git_name} <{existing_git_email}>")
            click.echo("Run `hogli devbox:setup --configure-git-identity` to change.")
        else:
            click.echo("Skipping Git identity setup.")
        return

    # Already saved -- skip unless explicitly asked to reconfigure
    if configure_git_identity is None and existing_git_name and existing_git_email:
        click.echo(f"Using saved Git identity: {existing_git_name} <{existing_git_email}>")
        click.echo("Run `hogli devbox:setup --configure-git-identity` to change.")
        return

    # Show prompts with best available defaults (saved > coder profile > empty)
    coder_git_name, coder_git_email = get_default_git_identity()
    default_git_name = existing_git_name or coder_git_name or ""
    default_git_email = existing_git_email or coder_git_email or ""

    click.echo()
    click.echo(click.style("Git identity", bold=True))
    click.echo("  Set the name and email used for Git commits inside your workspace.")
    click.echo("  These will be saved and reused for future workspaces.")
    click.echo()

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


def maybe_configure_dotfiles(configure_dotfiles: bool | None) -> None:
    """Optionally persist a dotfiles repo URL for new workspaces."""
    config = load_config()
    existing_uri = config.get("dotfiles_uri")

    if configure_dotfiles is False:
        if existing_uri:
            click.echo(f"Using saved dotfiles: {existing_uri}")
            click.echo("Run `hogli devbox:setup --configure-dotfiles` to change.")
        else:
            click.echo("Skipping dotfiles setup.")
        return

    if configure_dotfiles is None and existing_uri:
        click.echo(f"Using saved dotfiles: {existing_uri}")
        click.echo("Run `hogli devbox:setup --configure-dotfiles` to change.")
        return

    click.echo()
    click.echo(click.style("Dotfiles (optional)", bold=True))
    click.echo("  Personalize your workspace with a dotfiles repository.")
    click.echo("  The repo will be cloned and applied on every workspace start.")
    click.echo("  This will be saved and reused for future workspaces.")
    click.echo()

    dotfiles_uri = click.prompt(
        "Dotfiles repo URL",
        default=existing_uri or "",
        show_default=bool(existing_uri),
    ).strip()

    if dotfiles_uri:
        save_dotfiles_uri(dotfiles_uri)
        click.echo(f"Saved dotfiles repo for new workspaces: {dotfiles_uri}")
    else:
        click.echo("No dotfiles repo configured.")


@cli.command(name="devbox", help="Show available devbox commands")
def devbox_help() -> None:
    """Show the available `hogli devbox:*` commands."""
    commands = sorted(
        (name, cmd.help or "")
        for name, cmd in cli.commands.items()
        if name.startswith("devbox:") and not getattr(cmd, "hidden", False)
    )
    click.echo("Available devbox commands:")
    click.echo()
    for name, help_text in commands:
        click.echo(f"  hogli {name:<20} {help_text}")
    click.echo()
    click.echo("Run `hogli <command> --help` for command-specific options.")


def maybe_configure_claude_token(configure_claude: bool | None) -> None:
    """Optionally prompt for a Claude OAuth token and store it in Keychain."""
    if keychain.read(_CLAUDE_TOKEN_SERVICE) and configure_claude is not True:
        click.echo("Claude token: configured (stored in Keychain).")
        click.echo("Run `hogli devbox:setup --configure-claude` to replace.")
        return

    if not keychain.is_supported():
        click.echo("Claude token: set CLAUDE_OAUTH_TOKEN env var (Keychain not available on this platform).")
        return

    if configure_claude is False:
        click.echo("Skipping Claude token setup.")
        return

    click.echo()
    click.echo(click.style("Claude Code (optional)", bold=True))
    click.echo("  Workspaces can run Claude Code if you provide an OAuth token.")
    click.echo("  The token will be stored in your macOS Keychain and reused for future workspaces.")
    click.echo("  To generate one, run `claude setup-token` in another terminal.")
    click.echo("  You can also skip this and pass --claude-oauth-token later, or set CLAUDE_OAUTH_TOKEN.")
    click.echo()

    token = click.prompt(
        "Claude OAuth token (Enter to skip)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()

    if not token:
        click.echo("No token provided. Skipping.")
        return

    if keychain.write(_CLAUDE_TOKEN_SERVICE, token):
        click.echo("Saved to Keychain.")
    else:
        click.echo(click.style("Failed to save to Keychain.", fg="red"))


@cli.command(name="devbox:setup", help="Install and configure local access to Coder devboxes")
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
@click.option(
    "--configure-dotfiles/--skip-configure-dotfiles",
    default=None,
    help="Prompt for a dotfiles repo URL for new Coder workspaces",
)
@click.option(
    "--configure-claude/--skip-configure-claude",
    "configure_claude_setup",
    default=None,
    help="Prompt for a Claude OAuth token to store in Keychain",
)
def devbox_setup(
    configure_ssh: bool | None,
    configure_git_identity: bool | None,
    configure_dotfiles: bool | None,
    configure_claude_setup: bool | None,
) -> None:
    """Prepare this machine for Coder workspaces."""
    ensure_tailscale_connected("rerun `hogli devbox:setup`.")
    ensure_coder_installed()
    ensure_coder_authenticated()
    maybe_configure_ssh(configure_ssh=configure_ssh)
    maybe_configure_git_identity(configure_git_identity)
    maybe_configure_dotfiles(configure_dotfiles)
    maybe_configure_claude_token(configure_claude_setup)
    print_setup_summary()


@cli.command(name="devbox:list", help="List your devboxes")
def devbox_list() -> None:
    """List all workspaces belonging to the current user."""
    ensure_runtime_ready()
    workspaces = list_user_workspaces()

    if not workspaces:
        click.echo("No devboxes found. Run 'hogli devbox:start' to create one.")
        return

    click.echo(f"{'LABEL':<16} {'STATUS':<12} {'NAME'}")
    for ws in workspaces:
        ws_name = ws.get("name", "")
        label = extract_workspace_label(ws_name) or "(default)"
        status = get_workspace_status(ws)
        click.echo(f"  {label:<14} {click.style(status, fg=_workspace_status_color(status)):<20} {ws_name}")


@cli.command(name="devbox:start", help="Start or create your remote devbox")
@workspace_name_option
@click.option(
    "--disk",
    type=click.Choice(["60", "80", "100"]),
    default="100",
    help="Disk size in GiB (default: 100)",
)
@click.option(
    "--configure-claude/--skip-configure-claude",
    default=None,
    help="Prompt for a Claude OAuth token when creating a new workspace",
)
@click.option(
    "--claude-oauth-token",
    envvar="HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN",
    hidden=True,
)
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_start(
    workspace_label: str | None,
    disk: str,
    configure_claude: bool | None,
    claude_oauth_token: str | None,
    verbose: bool,
) -> None:
    """Start or create the remote devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)
    ws = get_workspace(name, workspaces or None)

    if ws is not None:
        _start_existing_workspace(name, ws, verbose=verbose)
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
        dotfiles_uri=config.get("dotfiles_uri"),
        verbose=verbose,
    )
    click.echo("Created.")
    _print_connection_info(name)


@cli.command(name="devbox:stop", help="Stop your devbox (preserves disk, stops billing)")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_stop(workspace_label: str | None, verbose: bool) -> None:
    """Stop the devbox. State is preserved on the EBS volume."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)
    ws = _get_workspace_or_fail(name, workspaces)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name, verbose=verbose)
    click.echo("Stopped. Disk preserved. Run 'hogli devbox:start' to resume.")


@cli.command(name="devbox:restart", help="Restart your devbox")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_restart(workspace_label: str | None, verbose: bool) -> None:
    """Stop and start the devbox in one step."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)
    _get_workspace_or_fail(name, workspaces)
    click.echo(f"Restarting '{name}'...")
    restart_workspace(name, verbose=verbose)
    click.echo("Restarted.")
    _print_connection_info(name)


@cli.command(name="devbox:update", help="Update devbox to the latest template")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_update(workspace_label: str | None, verbose: bool) -> None:
    """Apply the latest template to the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)
    ws = _get_workspace_or_fail(name, workspaces)
    if not ws.get("outdated"):
        click.echo(f"Devbox '{name}' is already up to date.")
        return
    click.echo(f"Updating '{name}' to the latest template...")
    update_workspace(name, verbose=verbose)
    click.echo("Updated.")
    _print_connection_info(name)


@cli.command(name="devbox:ssh", help="SSH into your devbox")
@workspace_name_option
def devbox_ssh(workspace_label: str | None) -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace_label)
    ssh_replace(name)


@cli.command(name="devbox:open", help="Open devbox in browser, VS Code, or Cursor")
@workspace_name_option
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--cursor", is_flag=True, help="Open in Cursor via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def devbox_open(workspace_label: str | None, vscode: bool, cursor: bool, web: bool) -> None:
    """Open the devbox in a browser or editor."""
    chosen = sum([vscode, cursor, web])
    if chosen > 1:
        raise click.UsageError("Choose one of `--vscode`, `--cursor`, or `--web`.")

    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace_label)

    if vscode:
        click.echo(f"Opening '{name}' in VS Code...")
        open_vscode(name)
    elif cursor:
        click.echo(f"Opening '{name}' in Cursor...")
        open_cursor(name)
    elif web:
        click.echo(f"Opening code-server for '{name}'...")
        open_web_ide(name)
    else:
        click.echo(f"Opening '{name}' in browser...")
        open_in_browser(name)


@cli.command(name="devbox:logs", help="Tail devbox build and agent logs")
@workspace_name_option
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def devbox_logs(workspace_label: str | None, follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace_label)
    logs_replace(name, follow)


@cli.command(name="devbox:destroy", help="Destroy your devbox and its data")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_destroy(workspace_label: str | None, verbose: bool) -> None:
    """Destroy the devbox completely."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)

    ws = get_workspace(name, workspaces or None)
    if ws is None:
        click.echo("No devbox found.")
        return

    if not click.confirm(f"Destroy '{name}'? This deletes the VM and its data"):
        click.echo("Cancelled.")
        return

    delete_workspace(name, verbose=verbose)
    click.echo("Destroyed.")


@cli.command(name="devbox:status", help="Show devbox status")
@workspace_name_option
def devbox_status(workspace_label: str | None) -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace_label)

    ws = get_workspace(name, workspaces or None)
    if ws is None:
        click.echo("No devbox found. Run 'hogli devbox:start' to create one.")
        return

    status = get_workspace_status(ws)

    click.echo(f"  Name:    {name}")
    click.echo(f"  Status:  {click.style(status, fg=_workspace_status_color(status))}")

    if ws.get("outdated"):
        click.echo(click.style("  Update:  template update available", fg="yellow"))
        click.echo("           Run `hogli devbox:update` to apply it.")

    # Show agent status if available
    resources = ws.get("latest_build", {}).get("resources", [])
    for resource in resources:
        for agent in resource.get("agents", []):
            agent_status = agent.get("status", "unknown")
            click.echo(f"  Agent:   {agent_status}")

    if status == "running":
        _print_connection_info(name)


@cli.command(name="devbox:forward", help="Forward PostHog UI to localhost")
@workspace_name_option
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def devbox_forward(workspace_label: str | None, port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace_label)
    if not _local_port_is_available(port):
        _fail(
            f"Local port {port} is already in use.\n"
            f"Stop the process using that port or rerun with `hogli devbox:forward --port {port + 1}`."
        )

    click.echo(f"Forwarding {name}:8010 -> localhost:{port}")
    click.echo(f"PostHog UI at http://localhost:{port}")
    click.echo("Ctrl+C to stop")
    click.echo()
    port_forward_replace(name, port, 8010)
