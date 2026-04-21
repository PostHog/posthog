"""`hogli start:wait` and `hogli start:stop` — thin wrappers around the
phrocs daemon's subcommands. The heavy lifting (polling, signal fallback,
log tailing) lives in the phrocs binary so the logic is single-sourced;
hogli delegates and propagates exit codes.
"""

from __future__ import annotations

import sys
import shutil
import subprocess

import click
from hogli.core.cli import cli


def _phrocs_bin() -> str | None:
    return shutil.which("phrocs")


@cli.command(name="start:wait", help="Wait for the headless dev stack to become ready")
@click.option("--timeout", default=300, type=int, show_default=True, help="Fail with exit 2 after this many seconds")
@click.option("--json", "as_json", is_flag=True, help="Emit a single JSON verdict line on stdout")
def wait_ready(timeout: int, as_json: bool) -> None:
    """Block until every process reports ready, then exit 0.

    Exit codes:

    \b
    0  all processes ready
    1  one or more processes crashed (tail logs printed)
    2  timeout elapsed while processes still starting
    3  daemon unreachable (phrocs not running, or socket path mismatch)
    """
    phrocs = _phrocs_bin()
    if phrocs is None:
        click.echo("phrocs binary not found — install it or run `hogli phrocs:build`", err=True)
        sys.exit(127)
    args = [phrocs, "wait", "--timeout", str(timeout)]
    if as_json:
        args.append("--json")
    sys.exit(subprocess.run(args, check=False).returncode)


@cli.command(name="start:stop", help="Stop the headless dev stack")
@click.option(
    "--timeout", default=15, type=int, show_default=True, help="Seconds to wait for graceful exit before SIGKILL"
)
def stop_headless(timeout: int) -> None:
    """Request a graceful shutdown via the IPC socket, then fall back to
    SIGTERM and finally SIGKILL if the daemon doesn't exit in time.

    Idempotent: exits 0 even when no daemon is running.
    """
    phrocs = _phrocs_bin()
    if phrocs is None:
        click.echo("phrocs binary not found — install it or run `hogli phrocs:build`", err=True)
        sys.exit(127)
    sys.exit(subprocess.run([phrocs, "stop", "--timeout", str(timeout)], check=False).returncode)
