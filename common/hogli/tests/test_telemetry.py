"""Tests for hogli telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli import telemetry
from hogli.core.cli import cli

_TELEMETRY_ENV_VARS = (
    "CI",
    "POSTHOG_TELEMETRY_OPT_OUT",
    "DO_NOT_TRACK",
    "POSTHOG_TELEMETRY_HOST",
    "POSTHOG_TELEMETRY_API_KEY",
)


@pytest.fixture(autouse=True)
def telemetry_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(telemetry, "get_config_path", lambda: config_path)
    for var in _TELEMETRY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return config_path


def test_is_enabled_by_default():
    assert telemetry.is_enabled() is True


@pytest.mark.parametrize(
    "env_vars, config",
    [
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {}),
        ({"DO_NOT_TRACK": "1"}, {}),
        ({"CI": "true"}, {}),
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {"enabled": True}),
    ],
)
def test_is_disabled(monkeypatch: pytest.MonkeyPatch, telemetry_config: Path, env_vars, config):
    if config:
        telemetry_config.write_text(json.dumps(config))
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    assert telemetry.is_enabled() is False


class TestAnonymousId:
    def test_stable_across_calls(self):
        first = telemetry.get_anonymous_id()
        second = telemetry.get_anonymous_id()
        assert first == second


class TestTrack:
    def test_queues_event_when_enabled(self, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=1.0)
            mock_send.assert_called_once()
            batch = mock_send.call_args[0][0]
            assert len(batch) == 1
            assert batch[0]["event"] == "command_completed"
            assert batch[0]["distinct_id"] == "test-id"
            assert batch[0]["properties"]["command"] == "test"

    def test_uses_env_overrides(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        with patch("hogli.telemetry.requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=2.0)
            mock_post.assert_called_once()
            assert mock_post.call_args[0][0] == "http://localhost/batch/"
            body = mock_post.call_args[1]["json"]
            assert body["api_key"] == "test-key"

    def test_noops_when_disabled(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False}))
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed")
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()

    def test_noops_when_notice_not_shown(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.track("command_completed")
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()

    def test_flush_noop_when_queue_empty(self):
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            telemetry.flush(timeout=1.0)
            mock_send.assert_not_called()


class TestFirstRunNotice:
    def test_creates_config(self, telemetry_config: Path):
        telemetry.show_first_run_notice_if_needed()
        assert telemetry_config.exists()
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is True
        assert config["first_run_notice_shown"] is True
        assert "anonymous_id" in config

    def test_shown_once(self, telemetry_config: Path, capsys):
        telemetry.show_first_run_notice_if_needed()
        captured_first = capsys.readouterr()
        assert "hogli collects anonymous usage data" in captured_first.err

        # Second call should produce no output
        telemetry.show_first_run_notice_if_needed()
        captured_second = capsys.readouterr()
        assert captured_second.err == ""


class TestTelemetryCommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_telemetry_off(self, runner, telemetry_config: Path):
        result = runner.invoke(cli, ["telemetry:off"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is False

    def test_telemetry_on(self, runner, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False}))
        result = runner.invoke(cli, ["telemetry:on"])
        assert result.exit_code == 0
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is True

    def test_telemetry_status_when_disabled_no_id_creation(self, runner, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False, "first_run_notice_shown": True}))
        result = runner.invoke(cli, ["telemetry:status"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        config = json.loads(telemetry_config.read_text())
        assert "anonymous_id" not in config


class TestInvokeTelemetry:
    def test_invoke_fires_started_and_completed_events(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        with patch.object(telemetry._client, "_send_batch") as mock_send:
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            assert result.exit_code == 0

            # Single batch call containing both events
            mock_send.assert_called_once()
            batch = mock_send.call_args[0][0]
            events = {e["event"] for e in batch}
            assert "command_started" in events
            assert "command_completed" in events

            started = next(e for e in batch if e["event"] == "command_started")
            assert started["properties"]["command"] == "quickstart"
            assert "is_ci" in started["properties"]

            completed = next(e for e in batch if e["event"] == "command_completed")
            assert completed["properties"]["command"] == "quickstart"
            assert completed["properties"]["exit_code"] == 0
            assert "duration_s" in completed["properties"]
            assert "is_ci" in completed["properties"]
