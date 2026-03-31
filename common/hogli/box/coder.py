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
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

import yaml
import click
from hogli.core.manifest import load_manifest

TEMPLATE_NAME = "posthog-linux"
BREW_PACKAGE = "coder/coder/coder"
RUNTIME_SETUP_HINT = "Run `hogli box:setup`."
CLAUDE_OAUTH_PARAMETER = "claude_oauth_token"

_STEP_RE = re.compile(r"^==>.*?(\w[\w ]+)")
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_WORKSPACE_PREFIX = "devbox"


def _fail(message: str) -> None:
    """Print a short actionable error and exit."""
    click.echo(click.style(message, fg="red"))
    raise SystemExit(1)


def get_coder_url() -> str:
    """Resolve the configured Coder deployment URL."""
    if url := os.environ.get("HOGLI_BOX_CODER_URL"):
        return url

    if url := os.environ.get("CODER_URL"):
        return url

    manifest = load_manifest()
    metadata = manifest.get("metadata", {})
    box_metadata = metadata.get("box", {})
    if isinstance(box_metadata, dict) and isinstance(box_metadata.get("coder_url"), str):
        return box_metadata["coder_url"]

    raise RuntimeError("Missing `metadata.box.coder_url` in common/hogli/manifest.yaml.")


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with consistent text handling."""
    return subprocess.run(args, capture_output=capture_output, text=True)


def _run_build(args: list[str], *, verbose: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a Coder build command with a spinner.

    In normal mode, shows a single-line spinner that updates with each
    build step. In verbose mode, streams all output including Terraform
    internals. On failure the full captured output is always printed.
    """
    import itertools
    import threading

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    captured: list[str] = []
    assert proc.stdout is not None

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
                    click.echo(f"\r  {next(frames)} {status}...", nl=False, err=True)
                stop_event.wait(0.08)
            if is_tty:
                click.echo(f"\r  {status}   ", err=True)

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


def _tailscale_status() -> dict[str, Any] | None:
    """Return parsed `tailscale status --json` output when available."""
    if not shutil.which("tailscale"):
        return None

    result = _run(["tailscale", "status", "--json"], capture_output=True)
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

    if shutil.which("tailscale"):
        _fail(f"Tailscale is not connected. Connect to the PostHog tailnet, then {setup_hint}")

    _fail(f"`tailscale` is not available. Start or install Tailscale, then {setup_hint}")


def _ssh_configured() -> bool:
    """Check if coder SSH config is present in ~/.ssh/config."""
    ssh_config = Path.home() / ".ssh" / "config"
    if not ssh_config.exists():
        return False

    return "# --- START CODER" in ssh_config.read_text()


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
    """Optionally install Coder SSH config in an explicit setup step."""
    if _ssh_configured():
        click.echo("Coder SSH config is already present.")
        return

    if configure_ssh is None:
        configure_ssh = click.confirm(
            "Configure SSH access for editors and local SSH clients?",
            default=True,
        )

    if not configure_ssh:
        click.echo("Skipping SSH config.")
        click.echo("Run `coder config-ssh` later if you want local SSH host entries.")
        return

    click.echo("Configuring SSH access...")
    result = _run(["coder", "config-ssh", "--yes"])
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def print_setup_summary() -> None:
    """Print a short summary after setup completes."""
    click.echo()
    click.echo("Setup complete.")
    click.echo("Workspace access from this machine uses `coder ssh` and optional SSH host entries.")
    click.echo("Git inside the workspace should use HTTPS via Coder external auth.")


def get_username() -> str:
    """Get current Coder username."""
    result = _coder_whoami()
    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            if isinstance(data, list):
                data = data[0]
            return data["username"]
        except (json.JSONDecodeError, KeyError):
            pass

    result = _run(["coder", "whoami"], capture_output=True)
    if result.returncode == 0:
        for line in result.stdout.strip().splitlines():
            stripped_line = line.strip()
            if stripped_line and not stripped_line.startswith("http"):
                return stripped_line.split()[0].split("@")[0].lower()

    _fail("Failed to determine the Coder username.")
    return ""


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
    result = _run(["coder", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return []

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    prefix = get_default_workspace_prefix()
    return [ws for ws in workspaces if ws.get("name") == prefix or ws.get("name", "").startswith(f"{prefix}-")]


def get_workspace(name: str) -> dict[str, Any] | None:
    """Get workspace info by name, or None if it does not exist."""
    result = _run(["coder", "list", "--output", "json"], capture_output=True)
    if result.returncode != 0:
        return None

    try:
        workspaces = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    for workspace in workspaces:
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
    repo: str = "https://github.com/PostHog/posthog",
    *,
    verbose: bool = False,
) -> None:
    """Create a new Coder workspace."""
    parameters = {
        "disk_size": str(disk_size),
        "repo": repo,
        CLAUDE_OAUTH_PARAMETER: claude_oauth_token or "",
    }

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
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, ["coder", "ssh", name])

    sys.exit(_run(["coder", "ssh", name]).returncode)


def port_forward_replace(name: str, local_port: int, remote_port: int) -> None:
    """Port-forward to a workspace and replace the current process."""
    args = ["coder", "port-forward", name, f"--tcp={local_port}:{remote_port}"]
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, args)

    sys.exit(_run(args).returncode)


def logs_replace(name: str, follow: bool) -> None:
    """Tail workspace logs and replace the current process."""
    args = ["coder", "logs", name]
    if follow:
        args.append("--follow")

    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, args)

    sys.exit(_run(args).returncode)


def run_in_workspace(
    name: str, command: list[str], *, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run a command in the workspace via `coder ssh`."""
    args = ["coder", "ssh", name, "--", *command]
    return _run(args, capture_output=capture_output)


def replace_with_workspace_command(name: str, command: list[str]) -> None:
    """Run a workspace command and replace the current process."""
    args = ["coder", "ssh", name, "--", *command]
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, args)

    sys.exit(_run(args).returncode)


def open_in_browser(name: str) -> None:
    """Open the workspace dashboard in the default browser."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}")


def open_vscode(name: str) -> None:
    """Open the workspace in VS Code Desktop via Coder."""
    coder_path = shutil.which("coder")
    if coder_path:
        os.execvp(coder_path, ["coder", "open", "vscode", name])

    sys.exit(_run(["coder", "open", "vscode", name]).returncode)


def open_web_ide(name: str) -> None:
    """Open code-server for the workspace."""
    username = get_username()
    webbrowser.open(f"{get_coder_url()}/@{username}/{name}/apps/code-server")
