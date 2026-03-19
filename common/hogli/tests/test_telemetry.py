"""Tests for hogli telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import patch

import click
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
    """Isolate every test from real config and env vars."""
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
    def test_fires_post_when_enabled(self, monkeypatch: pytest.MonkeyPatch, telemetry_config: Path):
        telemetry_config.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True})
        )
        monkeypatch.setenv("POSTHOG_TELEMETRY_HOST", "http://localhost")
        monkeypatch.setenv("POSTHOG_TELEMETRY_API_KEY", "test-key")
        with patch.object(telemetry, "_post_event") as mock_post:
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=1.0)
            mock_post.assert_called_once()
            host, payload = mock_post.call_args[0]
            assert host == "http://localhost"
            assert payload["api_key"] == "test-key"

    def test_noops_when_disabled(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": False}))
        with patch.object(telemetry, "_post_event") as mock_post:
            telemetry.track("command_completed")
            mock_post.assert_not_called()

    def test_noops_when_notice_not_shown(self, telemetry_config: Path):
        telemetry_config.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with patch.object(telemetry, "_post_event") as mock_post:
            telemetry.track("command_completed")
            mock_post.assert_not_called()


class TestFirstRunNotice:
    def test_creates_config(self, telemetry_config: Path):
        telemetry.show_first_run_notice_if_needed()
        assert telemetry_config.exists()
        config = json.loads(telemetry_config.read_text())
        assert config["enabled"] is True
        assert config["first_run_notice_shown"] is True
        assert "anonymous_id" in config

    def test_shown_once(self, telemetry_config: Path):
        telemetry.show_first_run_notice_if_needed()
        with patch.object(click, "echo") as mock_echo:
            telemetry.show_first_run_notice_if_needed()
            mock_echo.assert_not_called()


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
        with patch.object(telemetry, "_post_event") as mock_post:
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            telemetry.flush(timeout=1.0)
            assert result.exit_code == 0

            assert mock_post.call_count == 2
            payloads = [call[0][1] for call in mock_post.call_args_list]

            started = next(p for p in payloads if p["event"] == "command_started")
            assert started["properties"]["command"] == "quickstart"

            completed = next(p for p in payloads if p["event"] == "command_completed")
            assert completed["properties"]["command"] == "quickstart"
            assert completed["properties"]["exit_code"] == 0
            assert "duration_s" in completed["properties"]
