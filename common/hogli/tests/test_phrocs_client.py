from __future__ import annotations

import os
import hashlib
from pathlib import Path

import pytest

from hogli import phrocs_client


def test_socket_path_matches_sha256_prefix(tmp_path: Path) -> None:
    real = os.path.realpath(tmp_path)
    expected = f"/tmp/phrocs-{hashlib.sha256(real.encode()).hexdigest()[:8]}.sock"
    assert phrocs_client.socket_path(tmp_path) == expected


def test_socket_path_defaults_to_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert phrocs_client.socket_path() == phrocs_client.socket_path(tmp_path)


def test_pidfile_path_is_relative_to_cwd(tmp_path: Path) -> None:
    p = phrocs_client.pidfile_path(tmp_path)
    assert p == tmp_path / ".posthog" / ".generated" / "phrocs.pid"
