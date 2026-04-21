from __future__ import annotations

import pytest

from click.testing import CliRunner
from hogli.core.cli import cli


def _invoke(*args: str) -> tuple[int, str, str]:
    """Invoke the hogli CLI via CliRunner; returns (exit_code, stdout, stderr)."""
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(cli, list(args), catch_exceptions=False)
    # CliRunner captures SystemExit from sys.exit into result.exit_code.
    return result.exit_code, result.stdout, result.stderr


def test_wait_command_registered() -> None:
    code, out, err = _invoke("start:wait", "--help")
    assert code == 0
    assert "Wait for the headless dev stack" in out


def test_stop_command_registered() -> None:
    code, out, err = _invoke("start:stop", "--help")
    assert code == 0
    assert "Stop the headless dev stack" in out


def test_wait_reports_missing_phrocs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force shutil.which to return None so the "not installed" path runs.
    from hogli import headless

    monkeypatch.setattr(headless, "_phrocs_bin", lambda: None)
    code, out, err = _invoke("start:wait")
    assert code == 127
    assert "phrocs binary not found" in err


def test_stop_reports_missing_phrocs(monkeypatch: pytest.MonkeyPatch) -> None:
    from hogli import headless

    monkeypatch.setattr(headless, "_phrocs_bin", lambda: None)
    code, out, err = _invoke("start:stop")
    assert code == 127
    assert "phrocs binary not found" in err


def test_wait_propagates_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from hogli import headless

    fake_bin = "/usr/bin/true"  # ignored; we're stubbing subprocess.run below

    class _FakeResult:
        returncode = 2

    def fake_run(args, **kwargs):
        assert args[0] == fake_bin
        assert "wait" in args
        assert "--timeout" in args
        return _FakeResult()

    monkeypatch.setattr(headless, "_phrocs_bin", lambda: fake_bin)
    monkeypatch.setattr(headless.subprocess, "run", fake_run)
    code, _, _ = _invoke("start:wait", "--timeout", "10")
    assert code == 2


def test_wait_forwards_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from hogli import headless

    captured: dict[str, list[str]] = {}

    class _FakeResult:
        returncode = 0

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeResult()

    monkeypatch.setattr(headless, "_phrocs_bin", lambda: "/bin/phrocs")
    monkeypatch.setattr(headless.subprocess, "run", fake_run)
    _invoke("start:wait", "--json")
    assert "--json" in captured["args"]


def test_stop_forwards_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from hogli import headless

    captured: dict[str, list[str]] = {}

    class _FakeResult:
        returncode = 0

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _FakeResult()

    monkeypatch.setattr(headless, "_phrocs_bin", lambda: "/bin/phrocs")
    monkeypatch.setattr(headless.subprocess, "run", fake_run)
    _invoke("start:stop", "--timeout", "42")
    assert captured["args"][-2:] == ["--timeout", "42"]
