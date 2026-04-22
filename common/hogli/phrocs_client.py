"""Shared path derivations for the detached phrocs process.

Used by hogli tests and (eventually) the MCP server to compute the IPC
socket path and pidfile location without duplicating the hashing logic that
lives in Go. Kept intentionally minimal: the production `hogli start:wait`
and `hogli start:stop` commands shell out to the `phrocs` binary rather
than reimplementing the protocol in Python.
"""

from __future__ import annotations

import os
import hashlib
from pathlib import Path

GENERATED_SUBDIR = Path(".posthog") / ".generated"
PIDFILE_NAME = "phrocs.pid"


def socket_path(cwd: str | os.PathLike[str] | None = None) -> str:
    """Return the phrocs IPC socket path for `cwd` (defaults to cwd).

    Mirrors `ipc.SocketPathFor(wd)` in Go byte-for-byte: sha256 of the
    realpath, first 8 hex chars.
    """
    real = os.path.realpath(cwd if cwd is not None else os.getcwd())
    digest = hashlib.sha256(real.encode()).hexdigest()[:8]
    return f"/tmp/phrocs-{digest}.sock"


def pidfile_path(cwd: str | os.PathLike[str] | None = None) -> Path:
    """Return the phrocs pidfile path for `cwd`, relative to that directory."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / GENERATED_SUBDIR / PIDFILE_NAME


__all__ = ["socket_path", "pidfile_path"]
