"""Coder CLI wrapper for devbox management.

All subprocess interactions with the Coder CLI are isolated here.
"""

from __future__ import annotations

import os
import re
import sys
import json
import shutil
import tempfile
import itertools
import threading
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, NoReturn

import yaml
import click
from hogli.core.manifest import load_manifest

_MACOS_TAILSCALE_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TEMPLATE_NAME = "posthog-linux"
BREW_PACKAGE = "coder/coder/coder"
RUNTIME_SETUP_HINT = "Run `hogli devbox:setup`."
CLAUDE_OAUTH_PARAMETER = "claude_oauth_token"
GIT_NAME_PARAMETER = "git_name"
GIT_EMAIL_PARAMETER = "git_email"
DOTFILES_URI_PARAMETER = "dotfiles_uri"
DOTFILES_BRANCH_PARAMETER = "dotfiles_branch"
JETBRAINS_IDES_PARAMETER = "jetbrains_ides"

# Default values for all optional template parameters. Passing these explicitly
# prevents the Coder CLI from prompting interactively for missing values.
# Update this dict when new optional parameters are added to the template.
_TEMPLATE_PARAMETER_DEFAULTS: dict[str, str] = {
    DOTFILES_URI_PARAMETER: "",
    DOTFILES_BRANCH_PARAMETER: "",
    JETBRAINS_IDES_PARAMETER: "[]",
}

_STEP_RE = re.compile(r"^==>.*?(\w[\w ]+)")
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_WORKSPACE_PREFIX = "devbox"


class CoderUserInfo(dict[str, str]):
    """Normalized subset of Coder user fields used by hogli."""


def _fail(message: str) -> NoReturn:
    """Print a short actionable error and exit."""
    click.echo(click.style(message, fg="red"))
    raise SystemExit(1)


def get_coder_url() -> str:
    """Resolve the configured Coder deployment URL."""
    if url := os.environ.get("HOGLI_DEVBOX_CODER_URL"):
        return url

    if url := os.environ.get("CODER_URL"):
        return url

    manifest = load_manifest()
    metadata = manifest.get("metadata", {})
    devbox_metadata = metadata.get("devbox", {})
    if isinstance(devbox_metadata, dict) and isinstance(devbox_metadata.get("coder_url"), str):
        return devbox_metadata["coder_url"]

    raise RuntimeError("Missing `metadata.devbox.coder_url` in common/hogli/manifest.yaml.")


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with consistent text handling."""
    return subprocess.run(args, capture_output=capture_output, text=True)


def _run_or_exit(args: list[str]) -> None:
    """Replace the current process with a Coder command or exit with its status."""
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, args)

    sys.exit(_run(args).returncode)


def _run_build(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a Coder build command with a spinner.

    In normal mode, shows a single-line spinner that updates with each
    build step. In verbose mode, streams all output including Terraform
    internals. On failure the full captured output is always printed.
    """
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    captured: list[str] = []
    if proc.stdout is None:
        raise RuntimeError("Popen stdout pipe was not opened")

    if verbose:
        for line in proc.stdout:
            captured.append(line)
            click.echo(line, nl=False)
    else:
        is_tty = sys.stderr.isatty()
        status = "Starting"
        stop_event = threading.Event()
        frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])

        def _spin() -> None:
            while not stop_event.is_set():
                if is_tty:
                    click.echo(f"\r  {next(frames)} {status}...\033[K", nl=False, err=True)
                stop_event.wait(0.08)
            if is_tty:
                click.echo(f"\r  {status}\033[K", err=True)

        spinner = threading.Thread(target=_spin, daemon=True)
        spinner.start()

        for line in proc.stdout:
            captured.append(line)
            m = _STEP_RE.match(line)
            if m:
                status = m.group(1).strip()

        stop_event.set()
        spinner.join()

    returncode = proc.wait()

    if returncode != 0 and not verbose:
        click.echo()
        click.echo(click.style("Build failed. Full output:", fg="red"))
        for line in captured:
            click.echo(line, nl=False)

    return subprocess.CompletedProcess(args, returncode, "".join(captured), "")


def _run_with_rich_parameters(
    args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a Coder command with sensitive parameters passed via a temp YAML file.

    When verbose is None, runs without build filtering. When True/False,
    delegates to _run_build for spinner-based output.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as parameter_file:
        yaml.safe_dump(parameters, parameter_file)
        file_path = Path(parameter_file.name)

    try:
        file_path.chmod(0o600)
        full_args = [*args, "--rich-parameter-file", str(file_path)]
        if verbose is None:
            return _run(full_args)
        return _run_build(full_args, verbose=verbose)
    finally:
        file_path.unlink(missing_ok=True)


def _resolve_tailscale() -> str | None:
    """Return path to the tailscale CLI, checking PATH then the macOS app bundle."""
    if path := shutil.which("tailscale"):
        return path
    if sys.platform == "darwin" and os.path.isfile(_MACOS_TAILSCALE_CLI):
        return _MACOS_TAILSCALE_CLI
    return None


def _tailscale_env(tailscale_path: str) -> dict[str, str] | None:
    """Return extra env vars needed when invoking the macOS app bundle CLI."""
    if tailscale_path == _MACOS_TAILSCALE_CLI:
        return {**os.environ, "TAILSCALE_BE_CLI": "1"}
    return None


def _tailscale_status() -> dict[str, Any] | None:
    """Return parsed `tailscale status --json` output when available."""
    tailscale_path = _resolve_tailscale()
    if not tailscale_path:
        return None

    result = subprocess.run(
        [tailscale_path, "status", "--json"],
        capture_output=True,
        text=True,
        env=_tailscale_env(tailscale_path),
    )
    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def tailscale_connected() -> bool:
    """Check if Tailscale is running and connected."""
    status = _tailscale_status()
    return bool(status and status.get("BackendState") == "Running")


def ensure_tailscale_connected(setup_hint: str = RUNTIME_SETUP_HINT) -> None:
    """Fail fast when the Coder deployment is not reachable on the tailnet."""
    if tailscale_connected():
        return

    if _resolve_tailscale():
        _fail(f"Tailscale is not connected. Connect to the PostHog tailnet, then {setup_hint}")

    _fail(f"Tailscale is not installed. Install it, then {setup_hint}")


def _ssh_config_needs_update() -> bool:
    """Check whether ``coder config-ssh`` would make changes."""
    result = _run(["coder", "config-ssh", "--dry-run", "--yes"], capture_output=True)
    if result.returncode != 0:
        return True
    combined = result.stdout + result.stderr
    return "No changes to make" not in combined


def coder_installed() -> bool:
    """Return whether the Coder CLI is available."""
    return shutil.which("coder") is not None


def ensure_coder_installed() -> None:
    """Install Coder via Homebrew when available, otherwise print exact instructions."""
    if coder_installed():
        click.echo("coder CLI is installed.")
        return

    if not shutil.which("brew"):
        _fail(
            "`coder` is not installed.\n"
            "Install Homebrew, then run:\n"
            f"  brew install {BREW_PACKAGE}\n"
            "Or install Coder directly:\n"
            "  curl -L https://coder.com/install.sh | sh"
        )

    click.echo("Installing coder via Homebrew...")
    result = _run(["brew", "install", BREW_PACKAGE])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _coder_whoami() -> subprocess.CompletedProcess[str]:
    """Run `coder whoami` against the configured deployment."""
    return _run(["coder", "whoami", "--output", "json"], capture_output=True)


def _coder_user_show_me() -> subprocess.CompletedProcess[str]:
    """Run `coder users show me` against the configured deployment."""
    return _run(["coder", "users", "show", "me", "--output", "json"], capture_output=True)


def coder_authenticated() -> bool:
    """Return whether the local machine is authenticated with Coder."""
    if not coder_installed():
        return False

    return _coder_whoami().returncode == 0


def ensure_coder_authenticated() -> None:
    """Run interactive login when needed."""
    if coder_authenticated():
        click.echo("Coder login is ready.")
        return

    coder_url = get_coder_url()
    click.echo(f"Logging in to {coder_url}...")
    result = _run(["coder", "login", coder_url])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_runtime_ready() -> None:
    """Verify runtime prerequisites without mutating host setup."""
    ensure_tailscale_connected()

    if not coder_installed():
        _fail(f"`coder` is not installed. {RUNTIME_SETUP_HINT}")

    if not coder_authenticated():
        _fail(f"Coder login is not ready for {get_coder_url()}. {RUNTIME_SETUP_HINT}")


def maybe_configure_ssh(*, configure_ssh: bool | None) -> None:
    """Install Coder SSH config, skipping only when explicitly opted out."""
    if not _ssh_config_needs_update():
        click.echo("Coder SSH config is up to date.")
        return

    if configure_ssh is False:
        click.echo("Skipping SSH config.")
        click.echo("Run `coder config-ssh` later if you want local SSH host entries.")
        return

    click.echo("Adding Coder workspace entries to ~/.ssh/config...")
    result = _run(["coder", "config-ssh", "--yes"])
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    click.echo("Run `coder config-ssh --remove` to revert.")


def print_setup_summary() -> None:
    """Print a short summary after setup completes."""
    click.echo()
    click.echo("Setup complete. Run `hogli devbox:start` to create or start your devbox.")
    click.echo()
    click.echo("To reconfigure later:")
    click.echo("  hogli devbox:setup --configure-git-identity")
    click.echo("  hogli devbox:setup --configure-dotfiles")
    click.echo("  hogli devbox:setup --configure-claude")


def _first_non_empty_string(*values: Any) -> str | None:
    """Return the first non-empty string value."""
    for value in values:
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value:
                return stripped_value
    return None


def _parse_coder_user_info(payload: str) -> CoderUserInfo:
    """Parse JSON user payloads returned by the Coder CLI."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return CoderUserInfo()

    if isinstance(data, list):
        if not data:
            return CoderUserInfo()
        data = data[0]

    if not isinstance(data, dict):
        return CoderUserInfo()

    username = _first_non_empty_string(data.get("username"), data.get("name"))
    full_name = _first_non_empty_string(data.get("full_name"), data.get("fullName"), data.get("name"))
    email = _first_non_empty_string(data.get("email"))

    user_info = CoderUserInfo()
    if username:
        user_info["username"] = username
    if full_name:
        user_info["full_name"] = full_name
    if email:
        user_info["email"] = email
    return user_info


def get_coder_user_info() -> CoderUserInfo:
    """Return normalized user info for the authenticated Coder user when available."""
    for command in (_coder_user_show_me, _coder_whoami):
        result = command()
        if result.returncode != 0:
            continue

        user_info = _parse_coder_user_info(result.stdout)
        if user_info:
            return user_info

    result = _run(["coder", "whoami"], capture_output=True)
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith("http"):
                username = stripped_line.split()[0].split("@")[0].lower()
                if username:
                    return CoderUserInfo(username=username)

    return CoderUserInfo()


def get_default_git_identity() -> tuple[str | None, str | None]:
    """Return the default Git identity derived from the authenticated Coder profile."""
    user_info = get_coder_user_info()
    git_name = _first_non_empty_string(user_info.get("full_name"), user_info.get("username"))
    git_email = _first_non_empty_string(user_info.get("email"))
    return git_name, git_email


def get_username() -> str:
    """Get current Coder username."""
    user_info = get_coder_user_info()
    username = _first_non_empty_string(user_info.get("username"))
    if username:
        return username.lower()

    _fail("Failed to determine the Coder username.")


def get_workspace_name(label: str | None = None) -> str:
    """Derive workspace name from Coder username and optional label.

    Returns ``devbox-{username}`` for the default workspace, or
    ``devbox-{username}-{label}`` for a named workspace.
    """
    base = f"{_WORKSPACE_PREFIX}-{get_username()}"
    if label is None:
        return base
    if not _LABEL_RE.match(label):
        _fail(f"Invalid workspace label '{label}'. Use lowercase alphanumeric and hyphens.")
    return f"{base}-{label}"


def get_default_workspace_prefix() -> str:
    """Return the ``devbox-{username}`` prefix used to identify this user's workspaces."""
    return f"{_WORKSPACE_PREFIX}-{get_username()}"


def _list_workspaces() -> list[dict[str, Any]]:
    """Return raw workspace payloads from the Coder CLI."""
    result = _run(["coder", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return []

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return workspaces if isinstance(workspaces, list) else []


def extract_workspace_label(workspace_name: str) -> str | None:
    """Extract the label suffix from a full workspace name.

    Returns ``None`` for the default workspace (no label).
    """
    prefix = get_default_workspace_prefix()
    if workspace_name == prefix:
        return None
    if workspace_name.startswith(f"{prefix}-"):
        return workspace_name[len(prefix) + 1 :]
    return None


def list_user_workspaces() -> list[dict[str, Any]]:
    """Return all workspaces belonging to the current user with the devbox prefix."""
    prefix = get_default_workspace_prefix()
    return [ws for ws in _list_workspaces() if ws.get("name") == prefix or ws.get("name", "").startswith(f"{prefix}-")]


def get_workspace(name: str, workspaces: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Get workspace info by name, or None if it does not exist."""
    for workspace in workspaces if workspaces is not None else _list_workspaces():
        if workspace.get("name") == name:
            return workspace

    return None


def get_workspace_status(workspace: dict[str, Any]) -> str:
    """Extract status string from a workspace payload."""
    return workspace.get("latest_build", {}).get("status", "unknown")


def create_workspace(
    name: str,
    disk_size: int,
    claude_oauth_token: str | None = None,
    git_name: str | None = None,
    git_email: str | None = None,
    dotfiles_uri: str | None = None,
    repo: str = "https://github.com/PostHog/posthog",
    *,
    verbose: bool = False,
) -> None:
    """Create a new Coder workspace."""
    parameters = {
        **_TEMPLATE_PARAMETER_DEFAULTS,
        "disk_size": str(disk_size),
        "repo": repo,
        CLAUDE_OAUTH_PARAMETER: claude_oauth_token or "",
    }
    if git_name:
        parameters[GIT_NAME_PARAMETER] = git_name
    if git_email:
        parameters[GIT_EMAIL_PARAMETER] = git_email
    if dotfiles_uri:
        parameters[DOTFILES_URI_PARAMETER] = dotfiles_uri

    args = [
        "coder",
        "create",
        name,
        "--template",
        TEMPLATE_NAME,
        "--yes",
    ]
    result = _run_with_rich_parameters(args, parameters, verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def start_workspace(name: str, *, verbose: bool = False) -> None:
    """Start a stopped workspace."""
    result = _run_build(["coder", "start", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def stop_workspace(name: str, *, verbose: bool = False) -> None:
    """Stop a running workspace."""
    result = _run_build(["coder", "stop", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def restart_workspace(name: str, *, verbose: bool = False) -> None:
    """Restart a running workspace."""
    result = _run_build(["coder", "restart", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def update_workspace(
    name: str,
    parameters: dict[str, str] | None = None,
    *,
    verbose: bool = False,
) -> None:
    """Update a workspace to the latest template version."""
    merged = {**_TEMPLATE_PARAMETER_DEFAULTS, **(parameters or {})}
    args = ["coder", "update", name]
    result = _run_with_rich_parameters(args, merged, verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def delete_workspace(name: str, *, verbose: bool = False) -> None:
    """Delete a workspace."""
    result = _run_build(["coder", "delete", name, "--yes"], verbose=verbose)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def update_workspace_parameters(name: str, parameters: dict[str, str]) -> None:
    """Update mutable workspace parameters using a temp YAML file."""
    result = _run_with_rich_parameters(["coder", "update", name], parameters)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ssh_replace(name: str) -> None:
    """SSH into a workspace and replace the current process."""
    _run_or_exit(["coder", "ssh", name])


def port_forward_replace(name: str, local_port: int, remote_port: int) -> None:
    """Port-forward to a workspace and replace the current process."""
    _run_or_exit(["coder", "port-forward", name, f"--tcp={local_port}:{remote_port}"])


def logs_replace(name: str, follow: bool) -> None:
    """Tail workspace logs and replace the current process."""
    args = ["coder", "logs", name]
    if follow:
        args.append("--follow")

    _run_or_exit(args)


def run_in_workspace(
    name: str, command: list[str], *, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a command in the workspace via `coder ssh`."""
    args = ["coder", "ssh", name, "--", *command]
    return _run(args, capture_output=capture_output)


def replace_with_workspace_command(name: str, command: list[str]) -> None:
    """Run a workspace command and replace the current process."""
    _run_or_exit(["coder", "ssh", name, "--", *command])


def open_in_browser(name: str) -> None:
    """Open the workspace dashboard in the default browser."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}")


def open_vscode(name: str) -> None:
    """Open the workspace in VS Code Desktop via Coder."""
    _run_or_exit(["coder", "open", "vscode", name])


def open_cursor(name: str) -> None:
    """Open the workspace in Cursor via SSH remote."""
    cursor = shutil.which("cursor")
    if not cursor:
        _fail("`cursor` CLI is not on PATH. Open Cursor and enable Shell Integration from the Command Palette.")
    ssh_host = f"coder.{name}"
    os.execvp(cursor, ["cursor", "--remote", f"ssh-remote+{ssh_host}", "/home/coder/posthog"])


def open_web_ide(name: str) -> None:
    """Open code-server for the workspace."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}/apps/code-server")
