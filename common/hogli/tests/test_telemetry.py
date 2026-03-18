"""Tests for hogli telemetry."""

from __future__ import annotations

import os
import json

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli import telemetry
from hogli.core.cli import cli


@pytest.mark.parametrize(
    "env_vars, config, expected",
    [
        ({}, {}, True),
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {}, False),
        ({"DO_NOT_TRACK": "1"}, {}, False),
        ({"CI": "true"}, {}, False),
        ({"POSTHOG_TELEMETRY_OPT_OUT": "1"}, {"enabled": True}, False),
    ],
)
def test_is_enabled(tmp_path, env_vars, config, expected):
    config_path = tmp_path / "config.json"
    if config:
        config_path.write_text(json.dumps(config))
    with (
        patch.object(telemetry, "get_config_path", return_value=config_path),
        patch.dict(os.environ, env_vars),
    ):
        assert telemetry.is_enabled() is expected


class TestAnonymousId:
    def test_stable_across_calls(self, tmp_path):
        with patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"):
            first = telemetry.get_anonymous_id()
            second = telemetry.get_anonymous_id()
            assert first == second


class TestTrack:
    def test_fires_post_when_enabled(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict(
                os.environ,
                {"POSTHOG_TELEMETRY_HOST": "http://localhost", "POSTHOG_TELEMETRY_API_KEY": "test-key"},
                clear=False,
            ),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_completed", {"command": "test"})
            telemetry.flush(timeout=1.0)
            mock_post.assert_called_once()
            host, payload = mock_post.call_args[0]
            assert host == "http://localhost"
            assert payload["api_key"] == "test-key"

    def test_noops_when_disabled(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": False}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_completed")
            mock_post.assert_not_called()

    def test_noops_when_notice_not_shown(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_completed")
            mock_post.assert_not_called()


class TestFirstRunNotice:
    def test_creates_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.show_first_run_notice_if_needed()
            assert config_path.exists()
            config = json.loads(config_path.read_text())
            assert config["enabled"] is True
            assert config["first_run_notice_shown"] is True
            assert "anonymous_id" in config

    def test_shown_once(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.show_first_run_notice_if_needed()

            import click

            with patch.object(click, "echo") as mock_echo:
                telemetry.show_first_run_notice_if_needed()
                mock_echo.assert_not_called()


class TestTelemetryCommands:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_telemetry_off(self, runner, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:off"])
            assert result.exit_code == 0
            assert "disabled" in result.output.lower()
            config = json.loads(config_path.read_text())
            assert config["enabled"] is False

    def test_telemetry_on(self, runner, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": False}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:on"])
            assert result.exit_code == 0
            config = json.loads(config_path.read_text())
            assert config["enabled"] is True

    def test_telemetry_status_when_disabled_no_id_creation(self, runner, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": False, "first_run_notice_shown": True}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:status"])
            assert result.exit_code == 0
            assert "disabled" in result.output.lower()
            config = json.loads(config_path.read_text())
            assert "anonymous_id" not in config


class TestInvokeTelemetry:
    def test_invoke_fires_started_and_invoked_events(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict(
                os.environ,
                {"POSTHOG_TELEMETRY_HOST": "http://localhost", "POSTHOG_TELEMETRY_API_KEY": "test-key"},
                clear=False,
            ),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            runner = CliRunner()
            result = runner.invoke(cli, ["quickstart"])
            telemetry.flush(timeout=1.0)
            assert result.exit_code == 0

            assert mock_post.call_count == 2
            payloads = [call[0][1] for call in mock_post.call_args_list]

            started = next(p for p in payloads if p["event"] == "command_started")
            assert started["properties"]["command"] == "quickstart"

            invoked = next(p for p in payloads if p["event"] == "command_completed")
            assert invoked["properties"]["command"] == "quickstart"
            assert invoked["properties"]["exit_code"] == 0
            assert "duration_s" in invoked["properties"]
