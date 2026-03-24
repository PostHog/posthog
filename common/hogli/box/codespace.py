"""GitHub Codespaces subprocess wrapper.

Encapsulates all `gh codespace` CLI calls with proper error handling.
"""

from __future__ import annotations

import os
import sys
import json
import time
import subprocess
from typing import NoReturn

import click

REPO = "PostHog/posthog"


def _gh_env() -> dict[str, str]:
    """Return a copy of os.environ with GH_DEBUG suppressed."""
    env = os.environ.copy()
    env.pop("GH_DEBUG", None)
    return env


def _gh_json(cmd: list[str]) -> dict | list | None:
    """Run a gh command and parse JSON stdout. Returns None on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, env=_gh_env())
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def ensure_gh_authenticated() -> None:
    """Verify gh CLI is installed and authenticated. Exits on failure."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            env=_gh_env(),
        )
        if result.returncode != 0:
            click.echo("Error: GitHub CLI not authenticated.", err=True)
            click.echo("Run: gh auth login", err=True)
            raise SystemExit(1)
    except FileNotFoundError:
        click.echo("Error: GitHub CLI (gh) not found.", err=True)
        click.echo("Install: brew install gh", err=True)
        raise SystemExit(1)


def list_codespaces(repo: str = REPO) -> list[dict]:
    """List codespaces for a repo, parsed from JSON.

    Normalizes gh output so each entry has a top-level "branch" key
    (extracted from gitStatus.ref).
    """
    entries = _gh_json(
        [
            "gh",
            "codespace",
            "list",
            "--repo",
            repo,
            "--json",
            "name,state,gitStatus,machineName,lastUsedAt,displayName",
        ]
    )
    if not isinstance(entries, list):
        return []
    for entry in entries:
        entry["branch"] = entry.get("gitStatus", {}).get("ref", "")
    return entries


def find_codespace(repo: str, branch: str) -> dict | None:
    """Find an existing codespace for repo+branch. Prefers running over stopped."""
    matches = [e for e in list_codespaces(repo) if e.get("branch") == branch]
    if not matches:
        return None
    running = [e for e in matches if e.get("state") == "Available"]
    return running[0] if running else matches[0]


def create_codespace(
    repo: str,
    branch: str,
    machine: str,
    idle_timeout: str = "15m",
    retention: str = "720h",
    display_name: str | None = None,
) -> str:
    """Create a codespace and return its name."""
    cmd = [
        "gh",
        "codespace",
        "create",
        "--repo",
        repo,
        "--branch",
        branch,
        "--machine",
        machine,
        "--idle-timeout",
        idle_timeout,
        "--retention-period",
        retention,
    ]
    if display_name:
        cmd.extend(["--display-name", display_name])

    result = subprocess.run(cmd, capture_output=True, text=True, env=_gh_env())
    if result.returncode != 0:
        click.echo(f"Error creating codespace: {result.stderr.strip()}", err=True)
        raise SystemExit(1)

    return result.stdout.strip()


def start_codespace(name: str) -> None:
    """Start a stopped codespace."""
    subprocess.run(
        ["gh", "codespace", "start", "-c", name],
        env=_gh_env(),
        check=False,
    )


def stop_codespace(name: str) -> None:
    """Stop a running codespace."""
    subprocess.run(
        ["gh", "codespace", "stop", "-c", name],
        env=_gh_env(),
        check=False,
    )


def delete_codespace(name: str, force: bool = False) -> None:
    """Delete a codespace."""
    cmd = ["gh", "codespace", "delete", "-c", name]
    if force:
        cmd.append("--force")
    subprocess.run(cmd, env=_gh_env(), check=False)


def wait_for_codespace(name: str, timeout: int = 1800) -> bool:
    """Wait for a codespace to become Available. Returns True on success.

    Polls state every 5 seconds and prints status updates, matching
    the style of bin/wait-for-docker.
    """
    start_time = time.time()
    last_log = 0.0
    while time.time() - start_time < timeout:
        state = _check_state(name)
        if state == "Available":
            elapsed = int(time.time() - start_time)
            click.echo(f"Codespace ready after {elapsed}s.")
            return True
        if state in ("Failed", "Deleted"):
            click.echo(f"Codespace entered state: {state}", err=True)
            return False
        now = time.time()
        if now - last_log >= 5:
            elapsed = int(now - start_time)
            click.echo(f"Waiting for codespace: state={state} ({elapsed}s)")
            last_log = now
        time.sleep(3)
    return False


def _check_state(name: str) -> str:
    """Get the current state of a codespace."""
    info = _gh_json(["gh", "codespace", "view", "-c", name, "--json", "state"])
    if isinstance(info, dict):
        return info.get("state", "")
    return ""


def ssh_into(name: str) -> NoReturn:
    """SSH into a codespace. Replaces the current process."""
    os.execvp("gh", ["gh", "codespace", "ssh", "-c", name])
    sys.exit(1)  # unreachable, satisfies type checker


def open_in_vscode(name: str) -> NoReturn:
    """Open codespace in VS Code. Replaces the current process."""
    os.execvp("gh", ["gh", "codespace", "code", "-c", name])
    sys.exit(1)  # unreachable, satisfies type checker


def run_remote_command(name: str, command: str) -> None:
    """Execute a shell command inside a running codespace via SSH."""
    result = subprocess.run(
        ["gh", "codespace", "ssh", "-c", name, "--", "bash", "-lc", command],
        env=_gh_env(),
        check=False,
    )
    if result.returncode != 0:
        click.echo(f"Error: remote command failed (exit {result.returncode})", err=True)
        raise SystemExit(result.returncode)


def view_codespace(name: str) -> dict:
    """Get codespace details as a dict. Normalizes branch from gitStatus.ref."""
    info = _gh_json(
        [
            "gh",
            "codespace",
            "view",
            "-c",
            name,
            "--json",
            "name,state,gitStatus,machineName,createdAt,lastUsedAt,displayName",
        ]
    )
    if not isinstance(info, dict):
        return {}
    info["branch"] = info.get("gitStatus", {}).get("ref", "")
    return info


def get_current_branch() -> str:
    """Get the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "master"
