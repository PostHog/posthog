"""Coder CLI wrapper for devbox management.

All subprocess interactions with the Coder CLI are isolated here.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import subprocess
import webbrowser
from pathlib import Path

import click

TEMPLATE_NAME = "posthog-linux"
CODER_URL = "http://coder"


def _tailscale_connected() -> bool:
    """Check if Tailscale is running and connected."""
    ts = shutil.which("tailscale")
    if not ts:
        return False
    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
        return data.get("BackendState") == "Running"
    except (json.JSONDecodeError, KeyError):
        return False


def _ssh_configured() -> bool:
    """Check if coder SSH config is present in ~/.ssh/config."""
    ssh_config = Path.home() / ".ssh" / "config"
    if not ssh_config.exists():
        return False
    return "# --- START CODER" in ssh_config.read_text()


def ensure_coder() -> None:
    """Verify Tailscale, coder CLI, auth, and SSH config. Guides first-run setup interactively."""
    # 1. Tailscale must be connected (coder server is on the tailnet)
    if not _tailscale_connected():
        click.echo(click.style("Tailscale is not connected.", fg="red"))
        click.echo()
        click.echo("The Coder server is on the PostHog tailnet.")
        click.echo("Connect to Tailscale, then try again.")
        raise SystemExit(1)

    # 2. coder CLI must be installed
    if not shutil.which("coder"):
        click.echo(click.style("coder CLI not found.", fg="red"))
        click.echo()
        if shutil.which("brew"):
            if click.confirm("Install via Homebrew?", default=True):
                result = subprocess.run(["brew", "install", "coder/coder/coder"])
                if result.returncode != 0:
                    raise SystemExit(1)
                click.echo()
            else:
                click.echo("Install manually:")
                click.echo("  brew install coder/coder/coder")
                click.echo("  curl -L https://coder.com/install.sh | sh")
                raise SystemExit(1)
        else:
            click.echo("Install:")
            click.echo("  curl -L https://coder.com/install.sh | sh")
            raise SystemExit(1)

    # 3. Must be authenticated
    result = subprocess.run(
        ["coder", "whoami"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        click.echo(click.style("Not authenticated with Coder.", fg="red"))
        click.echo()
        if click.confirm("Log in now? (opens browser for Google SSO)", default=True):
            result = subprocess.run(["coder", "login", CODER_URL])
            if result.returncode != 0:
                raise SystemExit(1)
            click.echo()
        else:
            click.echo(f"Run manually: coder login {CODER_URL}")
            raise SystemExit(1)

    # 4. Auto-configure SSH (idempotent, no prompt needed)
    if not _ssh_configured():
        click.echo("Configuring SSH for Coder workspaces...")
        result = subprocess.run(
            ["coder", "config-ssh", "--yes"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            click.echo("SSH configured. VS Code Remote SSH will work automatically.")
        else:
            click.echo(click.style("Warning: could not configure SSH.", fg="yellow"))
            click.echo("Run manually: coder config-ssh")


def get_username() -> str:
    """Get current Coder username."""
    result = subprocess.run(
        ["coder", "whoami", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return data["username"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: parse text output (first non-empty line, strip email/whitespace)
    result = subprocess.run(
        ["coder", "whoami"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("http"):
                # Handle "username (email)" format
                return line.split()[0].split("@")[0].lower()

    click.echo(click.style("Failed to determine Coder username.", fg="red"))
    raise SystemExit(1)


def get_workspace_name() -> str:
    """Derive workspace name from Coder username."""
    return f"devbox-{get_username()}"


def get_workspace(name: str) -> dict | None:
    """Get workspace info by name, or None if it doesn't exist."""
    result = subprocess.run(
        ["coder", "list", "--output", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    for ws in workspaces:
        if ws.get("name") == name:
            return ws

    return None


def get_workspace_status(workspace: dict) -> str:
    """Extract status string from workspace dict."""
    return workspace.get("latest_build", {}).get("status", "unknown")


def create_workspace(name: str, disk_size: int, branch: str) -> None:
    """Create a new Coder workspace."""
    cmd = [
        "coder",
        "create",
        name,
        "--template",
        TEMPLATE_NAME,
        "--parameter",
        f"disk_size={disk_size}",
        "--parameter",
        f"repo={branch}",
        "--yes",
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def start_workspace(name: str) -> None:
    """Start a stopped workspace."""
    result = subprocess.run(["coder", "start", name, "--yes"])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def stop_workspace(name: str) -> None:
    """Stop a running workspace."""
    result = subprocess.run(["coder", "stop", name, "--yes"])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def delete_workspace(name: str) -> None:
    """Delete a workspace."""
    result = subprocess.run(["coder", "delete", name, "--yes"])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ssh_replace(name: str) -> None:
    """SSH into workspace. Replaces the current process."""
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, ["coder", "ssh", name])
    else:
        # Shouldn't reach here after ensure_coder(), but be safe
        sys.exit(subprocess.run(["coder", "ssh", name]).returncode)


def port_forward_replace(name: str, local_port: int, remote_port: int) -> None:
    """Port-forward to workspace. Replaces the current process."""
    coder_path = shutil.which("coder")
    args = ["coder", "port-forward", name, f"--tcp={local_port}:{remote_port}"]
    if coder_path:
        os.execvp(coder_path, args)
    else:
        sys.exit(subprocess.run(args).returncode)


def logs_replace(name: str, follow: bool) -> None:
    """Tail workspace logs. Replaces the current process."""
    coder_path = shutil.which("coder")
    args = ["coder", "logs", name]
    if follow:
        args.append("--follow")
    if coder_path:
        os.execvp(coder_path, args)
    else:
        sys.exit(subprocess.run(args).returncode)


def open_in_browser(name: str) -> None:
    """Open workspace dashboard in the default browser."""
    username = get_username()
    webbrowser.open(f"{CODER_URL}/@{username}/{name}")


def open_vscode(name: str) -> None:
    """Open workspace in VS Code Desktop via Coder SSH."""
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, ["coder", "open", "vscode", name])
    else:
        sys.exit(subprocess.run(["coder", "open", "vscode", name]).returncode)


def open_web_ide(name: str) -> None:
    """Open code-server (VS Code in browser) for the workspace."""
    username = get_username()
    webbrowser.open(f"{CODER_URL}/@{username}/{name}/apps/code-server")
