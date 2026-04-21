"""End-to-end phrocs daemon tests.

These exercise the real `phrocs` binary: spawn daemon → wait → stop. Skipped
when phrocs isn't on PATH so local and CI runs where only Python code is
available don't fail.
"""

from __future__ import annotations

import os
import time
import shutil
import subprocess
from pathlib import Path

import pytest

from hogli import phrocs_client


def _phrocs_bin() -> str | None:
    return shutil.which("phrocs")


requires_phrocs = pytest.mark.skipif(
    _phrocs_bin() is None,
    reason="phrocs binary not on PATH",
)


def _phrocs_supports_subcommands() -> bool:
    """Return True if the resolved phrocs understands the new wait/stop/daemon
    subcommands. Older phrocs builds (pre-headless) will error or hang."""
    bin_path = _phrocs_bin()
    if bin_path is None:
        return False
    try:
        result = subprocess.run(
            [bin_path, "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (result.stdout or "") + (result.stderr or "")
    return "wait" in text and "stop" in text


requires_daemon_phrocs = pytest.mark.skipif(
    not _phrocs_supports_subcommands(),
    reason="phrocs on PATH doesn't support daemon subcommands",
)


def _write_happy_config(path: Path) -> None:
    path.write_text(
        """procs:
  fast:
    shell: "echo READY; sleep 60"
    ready_pattern: "READY"
  slow:
    shell: "sleep 1; echo READY; sleep 60"
    ready_pattern: "READY"
"""
    )


def _write_crash_config(path: Path) -> None:
    path.write_text(
        """procs:
  ok:
    shell: "echo READY; sleep 60"
    ready_pattern: "READY"
  bad:
    shell: "echo about-to-die; sleep 0.2; exit 7"
    ready_pattern: "never"
"""
    )


def _wait_for_daemon_exit(cwd: Path, timeout: float = 10.0) -> bool:
    """Poll until the IPC socket disappears. Returns True on clean exit."""
    sock_path = phrocs_client.socket_path(cwd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not os.path.exists(sock_path):
            return True
        time.sleep(0.05)
    return False


@requires_phrocs
@requires_daemon_phrocs
def test_happy_path(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_happy_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    start = subprocess.run(
        [phrocs, "--daemon", "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert start.returncode == 0, start.stderr

    try:
        wait = subprocess.run(
            [phrocs, "wait", "--timeout", "15"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert wait.returncode == 0, f"wait stderr: {wait.stderr}, stdout: {wait.stdout}"
        assert "ready" in wait.stdout
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)

    assert _wait_for_daemon_exit(tmp_path)
    assert not phrocs_client.pidfile_path(tmp_path).exists()


@requires_phrocs
@requires_daemon_phrocs
def test_crashed_process_reports_exit_1(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_crash_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    subprocess.run([phrocs, "--daemon", "--config", str(config)], cwd=tmp_path, check=True, timeout=10)
    try:
        wait = subprocess.run(
            [phrocs, "wait", "--timeout", "10"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert wait.returncode == 1
        assert "bad" in wait.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)

    assert _wait_for_daemon_exit(tmp_path)


@requires_phrocs
@requires_daemon_phrocs
def test_stop_is_idempotent(tmp_path: Path) -> None:
    phrocs = _phrocs_bin()
    assert phrocs is not None

    # No daemon running at all — stop should still succeed.
    first = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert first.returncode == 0
    second = subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=5)
    assert second.returncode == 0


@requires_phrocs
@requires_daemon_phrocs
def test_second_instance_refused(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_happy_config(config)
    phrocs = _phrocs_bin()
    assert phrocs is not None

    first = subprocess.run(
        [phrocs, "--daemon", "--config", str(config)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert first.returncode == 0
    try:
        second = subprocess.run(
            [phrocs, "--daemon", "--config", str(config)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert second.returncode != 0
        assert "already running" in second.stderr
    finally:
        subprocess.run([phrocs, "stop"], cwd=tmp_path, capture_output=True, text=True, timeout=10)

    assert _wait_for_daemon_exit(tmp_path)
