"""Tests for hogli telemetry."""

from __future__ import annotations

import os
import json
import time

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli import telemetry
from hogli.core.cli import cli


class TestIsEnabled:
    def test_default_enabled(self, tmp_path):
        with patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"):
            assert telemetry.is_enabled() is True

    def test_opt_out_via_posthog_env(self, tmp_path):
        with (
            patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"),
            patch.dict(os.environ, {"POSTHOG_TELEMETRY_OPT_OUT": "1"}),
        ):
            assert telemetry.is_enabled() is False

    def test_opt_out_via_do_not_track_env(self, tmp_path):
        with (
            patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"),
            patch.dict(os.environ, {"DO_NOT_TRACK": "1"}),
        ):
            assert telemetry.is_enabled() is False

    def test_env_takes_precedence_over_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict(os.environ, {"POSTHOG_TELEMETRY_OPT_OUT": "1"}),
        ):
            assert telemetry.is_enabled() is False


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
            telemetry.track("command_invoked", {"command": "test"})
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
            telemetry.track("command_invoked")
            mock_post.assert_not_called()

    def test_noops_when_notice_not_shown(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_invoked")
            mock_post.assert_not_called()


class TestFlush:
    def test_respects_timeout(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True}))

        def slow_post(host, payload):
            time.sleep(5)

        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event", side_effect=slow_post),
        ):
            telemetry.track("test_event")
            start = time.monotonic()
            telemetry.flush(timeout=0.1)
            elapsed = time.monotonic() - start
            assert elapsed < 1.0


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
    def test_invoke_fires_telemetry_for_command(self, tmp_path):
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
            mock_post.assert_called_once()
            _, payload = mock_post.call_args[0]
            assert payload["event"] == "command_invoked"
            props = payload["properties"]
            assert props["command"] == "quickstart"
            assert props["exit_code"] == 0
            assert "duration_s" in props
