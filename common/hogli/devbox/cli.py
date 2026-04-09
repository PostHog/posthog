"""CLI commands for remote devbox management.

Provides hogli devbox:* commands for managing Coder-based remote dev environments.
"""

from __future__ import annotations

import os
import errno
import shutil
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import click
from hogli.core.cli import cli

from .coder import (
    GIT_EMAIL_PARAMETER,
    GIT_NAME_PARAMETER,
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
    ssh_replace,
    start_workspace,
    stop_workspace,
    update_workspace_parameters,
)
from .config import load_config, save_git_identity

WORKSPACE_STATUS_COLORS = {
    "running": "green",
    "stopped": "yellow",
    "starting": "cyan",
    "stopping": "yellow",
    "failed": "red",
    "deleting": "red",
}
PENDING_WORKSPACE_STATES = {"starting", "stopping", "deleting"}


def resolve_workspace_name(label: str | None) -> str:
    """Resolve a workspace name from an optional label."""
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


def _fail(message: str) -> NoReturn:
    """Print a short actionable error and exit."""
    click.echo(click.style(message, fg="red"))
    raise SystemExit(1)


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


def _get_workspace_or_fail(name: str) -> dict[str, Any]:
    """Return a workspace or exit with a consistent message when missing."""
    workspace = get_workspace(name)
    if workspace is not None:
        return workspace
    _fail("No devbox found. Run 'hogli devbox:start' to create one.")


def _workspace_status_color(status: str) -> str:
    """Return the display color for a workspace status."""
    return WORKSPACE_STATUS_COLORS.get(status, "white")


def _sync_git_identity_parameters(name: str) -> None:
    """Push local git identity config to workspace parameters before start."""
    config = load_config()
    git_name = config.get("git_name")
    git_email = config.get("git_email")
    if not git_name or not git_email:
        return
    update_workspace_parameters(
        name,
        {
            GIT_NAME_PARAMETER: git_name,
            GIT_EMAIL_PARAMETER: git_email,
        },
    )


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

    _sync_git_identity_parameters(name)

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


def _maybe_prompt_for_claude_oauth_token(configure_claude: bool | None) -> str | None:
    """Prompt for a Claude token when the user wants workspace auth configured."""
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


@cli.command(name="devbox", help="Show available Coder workspace commands")
def devbox_help() -> None:
    """Show the available `hogli devbox:*` commands."""
    click.echo("Available workspace commands:")
    click.echo()
    click.echo("  hogli devbox:setup       install and configure local access")
    click.echo("  hogli devbox:start       create or start your workspace")
    click.echo("  hogli devbox:list        list your workspaces")
    click.echo("  hogli devbox:ssh         open a shell in the workspace")
    click.echo("  hogli devbox:open        open the workspace in the browser")
    click.echo("  hogli devbox:forward     forward the PostHog UI to localhost")
    click.echo("  hogli devbox:logs        stream workspace logs")
    click.echo("  hogli devbox:status      show current workspace status")
    click.echo("  hogli devbox:stop        stop the workspace")
    click.echo("  hogli devbox:destroy     delete the workspace and its data")
    click.echo("  hogli devbox:cleanup:disk  free disk space (caches, build artifacts)")
    click.echo()
    click.echo("Run `hogli <command> --help` for command-specific options.")


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
def devbox_setup(configure_ssh: bool | None, configure_git_identity: bool | None) -> None:
    """Prepare this machine for Coder workspaces."""
    ensure_tailscale_connected("rerun `hogli devbox:setup`.")
    ensure_coder_installed()
    ensure_coder_authenticated()
    maybe_configure_ssh(configure_ssh=configure_ssh)
    maybe_configure_git_identity(configure_git_identity)
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
    name = resolve_workspace_name(workspace_label)
    ws = get_workspace(name)

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
    name = resolve_workspace_name(workspace_label)
    ws = _get_workspace_or_fail(name)

    status = get_workspace_status(ws)
    if status == "stopped":
        click.echo(f"Devbox '{name}' is already stopped.")
        return

    click.echo(f"Stopping '{name}'...")
    stop_workspace(name, verbose=verbose)
    click.echo("Stopped. Disk preserved. Run 'hogli devbox:start' to resume.")


@cli.command(name="devbox:ssh", help="SSH into your devbox")
@workspace_name_option
def devbox_ssh(workspace_label: str | None) -> None:
    """Open an SSH session to the devbox."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    ssh_replace(name)


@cli.command(name="devbox:open", help="Open devbox in browser or VS Code")
@workspace_name_option
@click.option("--vscode", is_flag=True, help="Open in VS Code Desktop via SSH")
@click.option("--web", is_flag=True, help="Open code-server (VS Code in browser)")
def devbox_open(workspace_label: str | None, vscode: bool, web: bool) -> None:
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


@cli.command(name="devbox:logs", help="Tail devbox build and agent logs")
@workspace_name_option
@click.option("-f", "--follow", is_flag=True, help="Follow log output")
def devbox_logs(workspace_label: str | None, follow: bool) -> None:
    """Tail workspace build and agent logs."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
    logs_replace(name, follow)


@cli.command(name="devbox:destroy", help="Destroy your devbox and its data")
@workspace_name_option
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_destroy(workspace_label: str | None, verbose: bool) -> None:
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


@cli.command(name="devbox:status", help="Show devbox status")
@workspace_name_option
def devbox_status(workspace_label: str | None) -> None:
    """Show the current state of the devbox."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)

    ws = get_workspace(name)
    if ws is None:
        click.echo("No devbox found. Run 'hogli devbox:start' to create one.")
        return

    status = get_workspace_status(ws)

    click.echo(f"  Name:    {name}")
    click.echo(f"  Status:  {click.style(status, fg=_workspace_status_color(status))}")

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


@cli.command(name="devbox:forward", help="Forward PostHog UI to localhost")
@workspace_name_option
@click.option("--port", default=8010, type=int, help="Local port to forward to")
def devbox_forward(workspace_label: str | None, port: int) -> None:
    """Forward the PostHog UI port to localhost."""
    ensure_runtime_ready()
    name = resolve_workspace_name(workspace_label)
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
