"""CLI commands for remote devbox management via GitHub Codespaces.

Provides hogli box:* commands for creating, managing, and connecting
to remote development environments.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import click
from hogli.core.cli import cli
from hogli.devenv import DevenvConfig

from . import codespace as cs

DEFAULT_MACHINE = "premiumLinux"
REMOTE_WORKSPACE_ROOT = "/workspaces/posthog"


def _get_devenv_config() -> DevenvConfig:
    """Read local devenv configuration. Falls back to product_analytics."""
    try:
        from hogli.devenv.generator import get_generated_mprocs_path, load_devenv_config

        output_path = get_generated_mprocs_path()
        config = load_devenv_config(output_path)
        if config and config.intents:
            return config
    except (FileNotFoundError, ImportError):
        pass
    return DevenvConfig(intents=["product_analytics"])


def _bootstrap_codespace(name: str, config: DevenvConfig) -> None:
    """Persist the desired config inside a newly created codespace and bootstrap it."""
    click.echo("Bootstrapping codespace from current hogli config...")
    bootstrap_args = ["uv", "run", "bin/hogli", "box:bootstrap"]

    for intent in config.intents:
        bootstrap_args.extend(["--intent", intent])
    for unit in config.include_units:
        bootstrap_args.extend(["--include-unit", unit])
    for unit in config.exclude_units:
        bootstrap_args.extend(["--exclude-unit", unit])
    for unit in config.skip_autostart:
        bootstrap_args.extend(["--skip-autostart", unit])
    for unit in config.enable_autostart:
        bootstrap_args.extend(["--enable-autostart", unit])
    if config.log_to_files:
        bootstrap_args.append("--log")

    remote_command = f"cd {shlex.quote(REMOTE_WORKSPACE_ROOT)} && {shlex.join(bootstrap_args)}"
    cs.run_remote_command(name, remote_command)


def _resolve_codespace_name(branch: str | None, name: str | None) -> str:
    """Resolve a codespace name from explicit name or branch lookup."""
    if name:
        return name
    branch = branch or cs.get_current_branch()
    existing = cs.find_codespace(cs.REPO, branch)
    if not existing:
        click.echo(f"No codespace found for branch: {branch}", err=True)
        click.echo("Run 'hogli box:start' to create one.", err=True)
        raise SystemExit(1)
    return existing["name"]


@cli.command(name="box:start", help="Create or reconnect to a remote devbox")
@click.option("--branch", "-b", default=None, help="Branch to use (default: current)")
@click.option("--intents", "-i", default=None, help="Comma-separated intents (default: from dev:setup config)")
@click.option("--machine", "-m", default=DEFAULT_MACHINE, help="Machine type")
@click.option("--code", is_flag=True, help="Open in VS Code instead of SSH")
@click.option("--new", "force_new", is_flag=True, help="Force create a new codespace")
@click.option("--display-name", "-d", default=None, help="Display name for the codespace")
def box_start(
    branch: str | None,
    intents: str | None,
    machine: str,
    code: bool,
    force_new: bool,
    display_name: str | None,
) -> None:
    """Create or reconnect to a remote devbox via GitHub Codespaces.

    Looks for an existing codespace on the current branch.
    If found, reconnects. If not, creates a new one.

    Intent configuration is read from your local hogli dev:setup config
    and passed to the codespace so the same services start remotely.
    """
    cs.ensure_gh_authenticated()
    branch = branch or cs.get_current_branch()
    config = _get_devenv_config()
    if intents:
        parsed_intents = [intent.strip() for intent in intents.split(",") if intent.strip()]
        config = config.model_copy(update={"intents": parsed_intents or config.intents})

    click.echo(f"Branch: {branch}")
    click.echo(f"Intents: {', '.join(config.intents)}")

    # Check for existing codespace
    if not force_new:
        existing = cs.find_codespace(cs.REPO, branch)
        if existing:
            name = existing["name"]
            state = existing.get("state", "unknown")
            click.echo(f"Found codespace: {name} ({state})")

            if state == "Shutdown":
                click.echo("Starting stopped codespace...")
                cs.start_codespace(name)

            if state != "Available":
                click.echo(f"Waiting for codespace to be ready (state={state})...")
                if not cs.wait_for_codespace(name):
                    click.echo(f"Codespace is still not ready: {name}", err=True)
                    click.echo("Reconnect later with: hogli box:start", err=True)
                    raise SystemExit(1)

            if code:
                click.echo("Opening in VS Code...")
                cs.open_in_vscode(name)
            else:
                click.echo("Connecting via SSH...")
                cs.ssh_into(name)

    # Create new codespace
    click.echo(f"Creating codespace (machine: {machine})...")
    name = cs.create_codespace(
        cs.REPO,
        branch,
        machine,
        display_name=display_name,
    )
    click.echo(f"Created: {name}")

    click.echo("Waiting for codespace to be ready (cold builds can take 10+ min)...")
    if not cs.wait_for_codespace(name):
        click.echo(f"Codespace is still provisioning: {name}", err=True)
        click.echo("Reconnect later with: hogli box:start", err=True)
        raise SystemExit(1)

    try:
        _bootstrap_codespace(name, config)
    except Exception as exc:
        click.echo(f"Error bootstrapping codespace: {exc}", err=True)
        raise SystemExit(1)

    click.echo("Codespace ready!")
    if code:
        click.echo("Opening in VS Code...")
        cs.open_in_vscode(name)
    else:
        click.echo("Connecting via SSH...")
        cs.ssh_into(name)


@cli.command(name="box:bootstrap", help="Bootstrap a new devbox from an explicit hogli config", hidden=True)
@click.option("--intent", "intents", multiple=True, help="Intent to persist in the remote dev config")
@click.option("--include-unit", "include_units", multiple=True, help="Additional unit to include")
@click.option("--exclude-unit", "exclude_units", multiple=True, help="Unit to exclude")
@click.option("--skip-autostart", "skip_autostart", multiple=True, help="Unit to leave stopped")
@click.option("--enable-autostart", "enable_autostart", multiple=True, help="Manual-start unit to auto-start")
@click.option("--log", "log_to_files", is_flag=True, help="Enable process log files")
def box_bootstrap(
    intents: tuple[str, ...],
    include_units: tuple[str, ...],
    exclude_units: tuple[str, ...],
    skip_autostart: tuple[str, ...],
    enable_autostart: tuple[str, ...],
    log_to_files: bool,
) -> None:
    """Persist an exact dev environment config in the current workspace and bootstrap it."""
    config = DevenvConfig(
        intents=list(intents) or ["product_analytics"],
        include_units=list(include_units),
        exclude_units=list(exclude_units),
        skip_autostart=list(skip_autostart),
        enable_autostart=list(enable_autostart),
        log_to_files=log_to_files,
    )

    from hogli.devenv.generator import MprocsGenerator
    from hogli.devenv.registry import create_mprocs_registry
    from hogli.devenv.resolver import IntentResolver, load_intent_map

    intent_map = load_intent_map()
    registry = create_mprocs_registry()
    resolver = IntentResolver(intent_map, registry)
    resolved = resolver.resolve(
        config.intents,
        include_units=config.include_units,
        exclude_units=config.exclude_units,
        skip_autostart=config.skip_autostart,
        enable_autostart=config.enable_autostart,
    )

    generator = MprocsGenerator(registry)
    generated_path = Path(REMOTE_WORKSPACE_ROOT) / ".posthog" / ".generated" / "mprocs.yaml"
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generator.generate_and_save(resolved, generated_path, config)
    click.echo(f"Generated dev config: {generated_path}")

    def _run(description: str, cmd: list[str], *, check: bool = True) -> None:
        click.echo(f"{description}...")
        result = subprocess.run(cmd, check=False)
        if check and result.returncode != 0:
            click.echo(f"Error: {description.lower()} failed (exit {result.returncode})", err=True)
            raise SystemExit(result.returncode)

    _run("Starting Docker infrastructure", ["uv", "run", "bin/hogli", "docker:services:up"])
    _run(
        "Waiting for PostgreSQL",
        ["timeout", "120", "bash", "-lc", "until pg_isready -h localhost -U posthog 2>/dev/null; do sleep 2; done"],
    )
    _run(
        "Waiting for ClickHouse",
        ["timeout", "120", "bash", "-lc", "until curl -sf http://localhost:8123/ping 2>/dev/null; do sleep 2; done"],
    )
    # Fast path: restore pre-migrated PG schema from CI before running migrations
    _run("Downloading pre-migrated schema from CI", ["uv", "run", "bin/hogli", "db:download-schema"], check=False)
    schema_file = Path(REMOTE_WORKSPACE_ROOT) / ".postgres-backups" / "schema-latest.sql.gz"
    if schema_file.exists():
        _run(
            "Restoring pre-migrated schema",
            ["bash", "-c", f"gunzip -c {schema_file} | psql -q -U posthog -h localhost posthog"],
            check=False,
        )

    _run("Running Django migrations", ["uv", "run", "python", "manage.py", "migrate", "--noinput"])
    _run("Running ClickHouse migrations", ["uv", "run", "python", "manage.py", "migrate_clickhouse"])
    _run("Creating dev API key", ["uv", "run", "python", "manage.py", "setup_local_api_key"])

    click.echo("Devbox bootstrap complete. Run 'hogli start' to launch app processes.")


@cli.command(name="box:stop", help="Stop a running devbox (preserves state)")
@click.option("--branch", "-b", default=None, help="Branch to find codespace for")
@click.argument("name", required=False)
def box_stop(branch: str | None, name: str | None) -> None:
    """Stop a running codespace. It can be restarted later."""
    cs.ensure_gh_authenticated()
    resolved = _resolve_codespace_name(branch, name)
    click.echo(f"Stopping: {resolved}")
    cs.stop_codespace(resolved)
    click.echo("Stopped.")


@cli.command(name="box:delete", help="Delete a devbox permanently")
@click.option("--branch", "-b", default=None, help="Branch to find codespace for")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.argument("name", required=False)
def box_delete(branch: str | None, force: bool, name: str | None) -> None:
    """Permanently delete a codespace and all its data."""
    cs.ensure_gh_authenticated()
    resolved = _resolve_codespace_name(branch, name)

    if not force:
        click.confirm(f"Delete codespace {resolved}?", abort=True)

    click.echo(f"Deleting: {resolved}")
    cs.delete_codespace(resolved, force=True)
    click.echo("Deleted.")


@cli.command(name="box:list", help="List your devboxes")
def box_list() -> None:
    """List all codespaces for the PostHog repo."""
    cs.ensure_gh_authenticated()
    codespaces = cs.list_codespaces()

    if not codespaces:
        click.echo("No codespaces found.")
        return

    click.echo(f"{'Name':<40} {'Branch':<25} {'State':<12} {'Machine':<15}")
    click.echo("-" * 92)
    for entry in codespaces:
        click.echo(
            f"{entry.get('name', ''):<40} "
            f"{entry.get('branch', ''):<25} "
            f"{entry.get('state', ''):<12} "
            f"{entry.get('machineName', ''):<15}"
        )


@cli.command(name="box:ssh", help="SSH into an existing devbox")
@click.option("--branch", "-b", default=None, help="Branch to find codespace for")
@click.argument("name", required=False)
def box_ssh(branch: str | None, name: str | None) -> None:
    """SSH into a running codespace."""
    cs.ensure_gh_authenticated()
    resolved = _resolve_codespace_name(branch, name)
    cs.ssh_into(resolved)


@cli.command(name="box:ports", help="Show forwarded ports from devbox")
@click.option("--branch", "-b", default=None, help="Branch to find codespace for")
@click.argument("name", required=False)
def box_ports(branch: str | None, name: str | None) -> None:
    """Show forwarded ports for a codespace."""
    cs.ensure_gh_authenticated()
    resolved = _resolve_codespace_name(branch, name)
    subprocess.run(["gh", "codespace", "ports", "-c", resolved], check=False)


@cli.command(name="box:status", help="Show devbox status and details")
@click.option("--branch", "-b", default=None, help="Branch to find codespace for")
@click.argument("name", required=False)
def box_status(branch: str | None, name: str | None) -> None:
    """Show status of a codespace."""
    cs.ensure_gh_authenticated()

    if not name:
        branch = branch or cs.get_current_branch()
        existing = cs.find_codespace(cs.REPO, branch)
        if not existing:
            click.echo(f"No codespace found for branch: {branch}")
            return
        name = existing["name"]

    info = cs.view_codespace(name)
    if not info:
        click.echo(f"Could not get details for: {name}", err=True)
        raise SystemExit(1)

    click.echo(f"Name:      {info.get('name', '')}")
    click.echo(f"Display:   {info.get('displayName', '')}")
    click.echo(f"State:     {info.get('state', '')}")
    click.echo(f"Branch:    {info.get('branch', '')}")
    click.echo(f"Machine:   {info.get('machineName', '')}")
    click.echo(f"Created:   {info.get('createdAt', '')}")
    click.echo(f"Last used: {info.get('lastUsedAt', '')}")
