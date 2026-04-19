"""CLI commands for remote devbox management.

Provides hogli devbox:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import os
import errno
import shutil
import socket
import functools
import subprocess
from collections.abc import Callable
from pathlib import Path
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
    ensure_tailscale_routes_accepted,
    extract_workspace_label,
    get_coder_user_info,
    get_default_git_identity,
    get_shared_users,
    get_sharing_status,
    get_workspace,
    get_workspace_name,
    get_workspace_status,
    list_coder_users,
    list_shared_workspaces,
    list_user_workspaces,
    logs_replace,
    maybe_configure_ssh,
    open_cursor,
    open_in_browser,
    open_vscode,
    open_web_ide,
    parse_workspace_target,
    port_forward_replace,
    print_setup_summary,
    restart_workspace,
    share_workspace,
    ssh_replace,
    start_workspace,
    stop_workspace,
    unshare_workspace,
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


def resolve_workspace_name(workspace: str | None) -> tuple[str, list[dict[str, Any]] | None]:
    """Resolve a workspace target into a full workspace name.

    Supports:
    - ``None`` -> user's default workspace (auto-selects when only one exists)
    - ``"@user"`` -> another user's default workspace
    - ``"@user/label"`` -> another user's labeled workspace
    - ``"label"`` -> current user's labeled workspace

    Returns (name, workspaces) where workspaces is the already-fetched list
    when available, so callers can skip a second ``_list_workspaces`` call.
    """
    if workspace is not None:
        return parse_workspace_target(workspace), None

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

    # No default among multiple -- require explicit workspace argument
    labels = [extract_workspace_label(ws["name"]) or "(default)" for ws in workspaces]
    _fail("Multiple workspaces found. Specify which one:\n" + "".join(f"  {lbl}\n" for lbl in labels))


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


def workspace_argument(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Shared Click decorator adding an optional ``WORKSPACE`` positional argument.

    Accepts a label for the current user's workspace, or ``@user[/label]``
    for another user's shared workspace.  ``--name`` / ``-n`` is accepted as
    an explicit alternative (e.g. ``--name api`` instead of just ``api``).
    """

    @click.argument("workspace", required=False, default=None)
    @click.option("--name", "-n", "workspace_name", default=None, help="Workspace label or @user[/label] target")
    @functools.wraps(fn)
    def wrapper(*args: Any, workspace: str | None = None, workspace_name: str | None = None, **kwargs: Any) -> Any:
        if workspace and workspace_name:
            raise click.UsageError("Pass WORKSPACE or --name, not both.")
        return fn(*args, workspace=workspace_name or workspace, **kwargs)

    return wrapper


def _print_connection_info(name: str) -> None:
    """Print connection commands after workspace is ready."""
    suffix = _workspace_arg_suffix(name)
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


def _workspace_arg_suffix(name: str) -> str:
    """Return the optional CLI suffix for a named workspace."""
    label = extract_workspace_label(name)
    return f" {label}" if label else ""


def _get_workspace_or_fail(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a workspace or exit with a consistent message when missing."""
    workspace = get_workspace(name, workspaces)
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


def _prompt_for_claude_token(*, skip_pause: bool = False) -> str | None:
    """Prompt for a Claude OAuth token and save it to Keychain."""
    if not skip_pause:
        click.echo("Run `claude setup-token` in another terminal to generate a token.")
        click.pause("Press Enter when you have the token ready...")
    token = click.prompt(
        "Claude OAuth token (Enter to skip)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    if not token:
        return None

    if keychain.write(_CLAUDE_TOKEN_SERVICE, token):
        click.echo("Saved to Keychain.")
    else:
        click.echo(click.style("Failed to save to Keychain.", fg="red"))
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

    if not _prompt_for_claude_token(skip_pause=True):
        click.echo("No token provided. Skipping.")


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
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_setup(
    configure_ssh: bool | None,
    configure_git_identity: bool | None,
    configure_dotfiles: bool | None,
    configure_claude_setup: bool | None,
    verbose: bool,
) -> None:
    """Prepare this machine for Coder workspaces."""
    ensure_tailscale_connected("rerun `hogli devbox:setup`.")
    ensure_tailscale_routes_accepted()
    ensure_coder_installed(verbose=verbose)
    ensure_coder_authenticated()
    maybe_configure_ssh(configure_ssh=configure_ssh, verbose=verbose)
    maybe_configure_git_identity(configure_git_identity)
    maybe_configure_dotfiles(configure_dotfiles)
    maybe_configure_claude_token(configure_claude_setup)
    print_setup_summary()


@cli.command(name="devbox:list", help="List your devboxes")
def devbox_list() -> None:
    """List all workspaces belonging to the current user, plus shared workspaces."""
    ensure_runtime_ready()
    workspaces = list_user_workspaces()

    if not workspaces:
        click.echo("No devboxes found. Run 'hogli devbox:start' to create one.")
    else:
        click.echo(f"{'LABEL':<16} {'STATUS':<12} {'NAME'}")
        for ws in workspaces:
            ws_name = ws.get("name", "")
            label = extract_workspace_label(ws_name) or "(default)"
            status = get_workspace_status(ws)
            click.echo(f"  {label:<14} {click.style(status, fg=_workspace_status_color(status)):<20} {ws_name}")

    shared = list_shared_workspaces()
    if shared:
        click.echo()
        click.echo("Shared with you:")
        for ws in shared:
            ws_name = ws.get("name", "")
            status = get_workspace_status(ws)
            owner = ws.get("owner_name", "unknown")
            click.echo(f"  {ws_name:<30} {click.style(status, fg=_workspace_status_color(status)):<20} (from {owner})")

    shared_out: list[tuple[str, list[str]]] = []
    for ws in workspaces:
        ws_name = ws.get("name", "")
        users = get_shared_users(ws_name)
        if users:
            shared_out.append((ws_name, users))
    if shared_out:
        click.echo()
        click.echo("Shared with others:")
        for ws_name, users in shared_out:
            label = extract_workspace_label(ws_name) or "(default)"
            click.echo(f"  {label:<16} {', '.join(users)}")


@cli.command(name="devbox:users", help="List Coder users (for devbox sharing)")
def devbox_users() -> None:
    """List all active Coder users so you know who to share with."""
    ensure_runtime_ready()

    current_user = get_coder_user_info()
    current_username = current_user.get("username", "")

    users = list_coder_users()
    if not users:
        _fail("Could not fetch users. Check your Coder authentication.")

    users.sort(key=lambda u: u.get("username", ""))

    click.echo(f"  {'USERNAME':<16} {'NAME':<30} {'EMAIL'}")
    for user in users:
        username = user.get("username", "")
        name = user.get("name", "")
        email = user.get("email", "")
        is_you = username == current_username
        name_col = f"{'(you)' if is_you else name:<30}"
        if is_you:
            name_col = click.style(name_col, fg="green")
        click.echo(f"  {username:<16} {name_col} {email}")


def _hint_if_positional_looks_like_username(
    command: str, workspace: str | None, users: tuple[str, ...], list_sharing: bool = False
) -> None:
    """Warn when the positional arg is almost certainly meant as a target username.

    The positional slot on every `devbox:*` command selects a workspace label,
    not a user. Share/unshare take `--user` for the target, so this case is a
    common footgun.
    """
    if workspace and not users and not list_sharing:
        raise click.UsageError(
            f"Pass the target user with --user (e.g. `hogli {command} --user {workspace}`).\n"
            "The positional argument selects one of YOUR workspaces. Run 'hogli devbox:users' to find usernames."
        )


@cli.command(name="devbox:share", help="Share your devbox with other users")
@workspace_argument
@click.option("--user", "users", multiple=True, help="Coder username(s) to share with")
@click.option("--role", type=click.Choice(["use", "admin"]), default="use", help="Access role to grant")
@click.option("--list", "list_sharing", is_flag=True, help="Show who has access")
def devbox_share(
    workspace: str | None,
    users: tuple[str, ...],
    role: str,
    list_sharing: bool,
) -> None:
    """Share your devbox with other Coder users."""
    ensure_runtime_ready()
    _hint_if_positional_looks_like_username("devbox:share", workspace, users, list_sharing)

    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)

    if list_sharing:
        result = get_sharing_status(name)
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        click.echo(result.stdout)
        return

    if not users:
        raise click.UsageError("Specify at least one --user. Run 'hogli devbox:users' to find usernames.")

    share_workspace(name, list(users), role)
    click.echo(f"Shared '{name}' with {', '.join(users)} (role: {role}).")


@cli.command(name="devbox:unshare", help="Revoke access to your devbox from other users")
@workspace_argument
@click.option("--user", "users", multiple=True, help="Coder username(s) to revoke access from")
def devbox_unshare(workspace: str | None, users: tuple[str, ...]) -> None:
    """Revoke access to your devbox from one or more Coder users."""
    ensure_runtime_ready()
    _hint_if_positional_looks_like_username("devbox:unshare", workspace, users)

    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)

    if not users:
        raise click.UsageError("Specify at least one --user. Run 'hogli devbox:share --list' to see current access.")

    user_list = list(users)
    unshare_workspace(name, user_list)
    click.echo(f"Revoked access for: {', '.join(user_list)}")
    click.echo(click.style("Restart your devbox for this to take effect.", fg="yellow"))


@cli.command(name="devbox:start", help="Start or create your remote devbox")
@workspace_argument
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
    workspace: str | None,
    disk: str,
    configure_claude: bool | None,
    claude_oauth_token: str | None,
    verbose: bool,
) -> None:
    """Start or create the remote devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    ws = get_workspace(name, workspaces)

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
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_stop(workspace: str | None, verbose: bool) -> None:
    """Stop the devbox. State is preserved on the EBS volume."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    ws = _get_workspace_or_fail(name, workspaces)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name, verbose=verbose)
    click.echo("Stopped. Disk preserved. Run 'hogli devbox:start' to resume.")


@cli.command(name="devbox:restart", help="Restart your devbox")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_restart(workspace: str | None, verbose: bool) -> None:
    """Stop and start the devbox in one step."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    _get_workspace_or_fail(name, workspaces)
    click.echo(f"Restarting '{name}'...")
    restart_workspace(name, verbose=verbose)
    click.echo("Restarted.")
    _print_connection_info(name)


@cli.command(name="devbox:update", help="Update devbox to the latest template")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_update(workspace: str | None, verbose: bool) -> None:
    """Apply the latest template to the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)
    ws = _get_workspace_or_fail(name, workspaces)
    if not ws.get("outdated"):
        click.echo(f"Devbox '{name}' is already up to date.")
        return
    config = load_config()
    params: dict[str, str] = {}
    if dotfiles_uri := config.get("dotfiles_uri"):
        params[DOTFILES_URI_PARAMETER] = dotfiles_uri
    click.echo(f"Updating '{name}' to the latest template...")
    update_workspace(name, parameters=params, verbose=verbose)
    click.echo("Updated.")
    _print_connection_info(name)


@cli.command(name="devbox:ssh", help="SSH into your devbox")
@workspace_argument
def devbox_ssh(workspace: str | None) -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    ssh_replace(name)


@cli.command(name="devbox:open", help="Open devbox in browser, VS Code, or Cursor")
@workspace_argument
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--cursor", is_flag=True, help="Open in Cursor via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def devbox_open(workspace: str | None, vscode: bool, cursor: bool, web: bool) -> None:
    """Open the devbox in a browser or editor."""
    chosen = sum([vscode, cursor, web])
    if chosen > 1:
        raise click.UsageError("Choose one of `--vscode`, `--cursor`, or `--web`.")

    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)

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
@workspace_argument
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def devbox_logs(workspace: str | None, follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    logs_replace(name, follow)


@cli.command(name="devbox:destroy", help="Destroy your devbox and its data")
@workspace_argument
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_destroy(workspace: str | None, verbose: bool) -> None:
    """Destroy the devbox completely."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)

    ws = get_workspace(name, workspaces)
    if ws is None:
        click.echo("No devbox found.")
        return

    if not click.confirm(f"Destroy '{name}'? This deletes the VM and its data"):
        click.echo("Cancelled.")
        return

    delete_workspace(name, verbose=verbose)
    click.echo("Destroyed.")


@cli.command(name="devbox:status", help="Show devbox status")
@workspace_argument
def devbox_status(workspace: str | None) -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name, workspaces = resolve_workspace_name(workspace)

    ws = get_workspace(name, workspaces)
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
@workspace_argument
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def devbox_forward(workspace: str | None, port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
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


def _gib(nbytes: int) -> str:
    return f"{nbytes / 1024**3:.1f}G"


def _snapshot_free(paths: list[Path]) -> dict[int, int]:
    """Return free bytes keyed by device ID, deduplicating paths on the same filesystem."""
    seen: dict[int, int] = {}
    for path in paths:
        try:
            dev = path.stat().st_dev
            if dev not in seen:
                seen[dev] = shutil.disk_usage(path).free
        except OSError:
            pass
    return seen


def _sum_freed(before: dict[int, int], after: dict[int, int]) -> int:
    """Sum free-space gains across all watched devices."""
    return sum(max(0, after[dev] - before[dev]) for dev in after if dev in before)


def _run_cleanup_step(label: str, cmd: list[str]) -> None:
    """Run a cleanup command and print its label."""
    click.echo(f"  {label}...", nl=False)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        click.echo(" done")
    except FileNotFoundError:
        click.echo(" skipped (command unavailable)")
    except subprocess.CalledProcessError as e:
        click.echo(f" warning: exited with code {e.returncode}")


def _rm_dir(label: str, path: Path) -> None:
    """Delete a directory and print its label."""
    if not path.exists():
        click.echo(f"  {label}... skipped (not found)")
        return
    click.echo(f"  {label}...", nl=False)
    try:
        shutil.rmtree(path)
        click.echo(" done")
    except OSError as e:
        click.echo(f" warning: partial deletion ({e})")


@cli.command(name="devbox:cleanup:disk", help="Free disk space by cleaning caches and build artifacts")
@click.option("--docker", "prune_docker", is_flag=True, help="Also prune stopped Docker containers")
@click.option(
    "--cargo",
    "prune_cargo",
    is_flag=True,
    help="Also remove Cargo build artifacts (forces full Rust recompile on next build)",
)
def devbox_cleanup_disk(prune_docker: bool, prune_cargo: bool) -> None:
    """Free disk space by removing caches and build artifacts that are safe to delete.

    The default run is safe: it only removes orphaned packages, download caches,
    and old Nix generations — none of which force a full rebuild on next use.
    Use --cargo to also remove Cargo build artifacts (forces full Rust recompile).
    Use --docker to also prune stopped containers.
    """
    home = Path.home()
    # Watch distinct filesystems: home covers uv/sccache/cargo; /nix covers Nix store
    # (may be a separate volume); / covers Docker storage and anything else.
    watch_paths = [p for p in [home, Path("/nix"), Path("/")] if p.exists()]
    before = _snapshot_free(watch_paths)

    click.echo("Cleaning caches and build artifacts...")
    click.echo()

    # uv wheel/sdist cache
    _run_cleanup_step("uv cache (~/.cache/uv)", ["uv", "cache", "clean"])

    # sccache compiler cache
    _rm_dir("sccache (~/.cache/sccache)", home / ".cache" / "sccache")

    # pnpm orphaned store entries
    _run_cleanup_step("pnpm store (orphaned packages)", ["pnpm", "store", "prune"])

    click.echo("  Nix garbage collection (old generations)...", nl=False)
    try:
        subprocess.run(["nix-collect-garbage", "-d"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        click.echo(" done")
    except FileNotFoundError:
        click.echo(" skipped (nix-collect-garbage unavailable)")
    except subprocess.CalledProcessError as e:
        click.echo(f" warning: exited with code {e.returncode}")

    # Cargo build artifacts — opt-in because removing them forces a full Rust recompile
    if prune_cargo:
        _rm_dir("Cargo build artifacts (~/.cargo/target)", home / ".cargo" / "target")

    if prune_docker:
        click.echo("  Docker stopped containers...", nl=False)
        try:
            subprocess.run(
                ["docker", "container", "prune", "-f"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )  # noqa: S603
            click.echo(" done")
        except FileNotFoundError:
            click.echo(" skipped (docker unavailable)")
        except subprocess.CalledProcessError as e:
            click.echo(f" warning: exited with code {e.returncode}")

    actually_freed = _sum_freed(before, _snapshot_free(watch_paths))

    click.echo()
    if actually_freed > 0:
        click.echo(click.style(f"Freed {_gib(actually_freed)} of disk space.", fg="green"))
    else:
        click.echo("Nothing significant was freed (caches may already be empty).")

    tips = []
    if not prune_cargo:
        tips.append("  hogli devbox:cleanup:disk --cargo  (rm ~/.cargo/target, forces recompile)")
    if not prune_docker:
        tips.append("  hogli devbox:cleanup:disk --docker  (prune stopped containers)")
    if tips:
        click.echo()
        click.echo("Tips for more space:")
        for tip in tips:
            click.echo(tip)
