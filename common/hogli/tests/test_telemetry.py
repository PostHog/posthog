"""Tests for hogli telemetry."""

from __future__ import annotations

import os
import json
import time
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

os.environ["DJANGO_SKIP_MIGRATIONS"] = "true"

from hogli import telemetry
from hogli.core.cli import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_pending_threads():
    telemetry._pending_threads.clear()
    yield
    telemetry._pending_threads.clear()


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

    def test_opt_out_via_do_not_track(self, tmp_path):
        with (
            patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"),
            patch.dict(os.environ, {"DO_NOT_TRACK": "1"}),
        ):
            assert telemetry.is_enabled() is False

    def test_opt_out_via_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": False}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            assert telemetry.is_enabled() is False

    def test_env_takes_precedence_over_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict(os.environ, {"POSTHOG_TELEMETRY_OPT_OUT": "1"}),
        ):
            assert telemetry.is_enabled() is False


class TestGetAnonymousId:
    def test_generates_valid_uuid(self, tmp_path):
        with patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"):
            anon_id = telemetry.get_anonymous_id()
            uuid.UUID(anon_id)  # raises if invalid

    def test_stable_across_calls(self, tmp_path):
        with patch.object(telemetry, "get_config_path", return_value=tmp_path / "config.json"):
            first = telemetry.get_anonymous_id()
            second = telemetry.get_anonymous_id()
            assert first == second

    def test_persisted_to_disk(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            anon_id = telemetry.get_anonymous_id()
            config = json.loads(config_path.read_text())
            assert config["anonymous_id"] == anon_id


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
            assert len(telemetry._pending_threads) == 1
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
            assert len(telemetry._pending_threads) == 0
            mock_post.assert_not_called()

    def test_correct_payload_structure(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"enabled": True, "anonymous_id": "test-id-123", "first_run_notice_shown": True})
        )
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict(os.environ, {"POSTHOG_TELEMETRY_API_KEY": "test-key"}, clear=False),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_invoked", {"command": "test"})
            telemetry.flush(timeout=1.0)
            host, payload = mock_post.call_args[0]
            assert payload["api_key"] == "test-key"
            assert payload["distinct_id"] == "test-id-123"
            assert payload["event"] == "command_invoked"
            assert payload["properties"]["$process_person_profile"] is False
            assert payload["properties"]["$groups"] == {"project": "hogli"}
            assert payload["properties"]["command"] == "test"
            assert "timestamp" in payload

    def test_noops_when_notice_not_shown(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event") as mock_post,
        ):
            telemetry.track("command_invoked")
            assert len(telemetry._pending_threads) == 0
            mock_post.assert_not_called()

    def test_never_raises_on_http_failure(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id"}))
        mock_requests = MagicMock()
        mock_requests.post.side_effect = Exception("connection failed")
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.dict("sys.modules", {"requests": mock_requests}),
        ):
            # Should not raise
            telemetry._post_event("http://localhost", {"api_key": "k", "event": "e"})

    def test_never_raises_on_corrupt_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text("not json")
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            # is_enabled returns True (default), get_anonymous_id creates new one
            # Should not raise
            telemetry.track("command_invoked")


class TestFlush:
    def test_joins_pending_threads(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "test-id", "first_run_notice_shown": True}))
        with (
            patch.object(telemetry, "get_config_path", return_value=config_path),
            patch.object(telemetry, "_post_event"),
        ):
            telemetry.track("test_event")
            assert len(telemetry._pending_threads) > 0
            telemetry.flush(timeout=1.0)
            assert len(telemetry._pending_threads) == 0

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

    def test_noops_when_no_pending(self):
        telemetry.flush(timeout=1.0)  # Should not raise


class TestFirstRunNotice:
    def test_prints_notice_to_stderr(self, tmp_path):
        config_path = tmp_path / "sub" / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            import click

            with patch.object(click, "echo", wraps=click.echo) as mock_echo:
                telemetry.show_first_run_notice_if_needed()
                mock_echo.assert_called()
                # Check it was called with err=True
                _, kwargs = mock_echo.call_args
                assert kwargs.get("err") is True

    def test_creates_config(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.show_first_run_notice_if_needed()
            assert config_path.exists()
            config = json.loads(config_path.read_text())
            assert config["enabled"] is True
            assert config["first_run_notice_shown"] is True
            assert "anonymous_id" in config

    def test_noops_on_second_call(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.show_first_run_notice_if_needed()

            import click

            with patch.object(click, "echo") as mock_echo:
                telemetry.show_first_run_notice_if_needed()
                mock_echo.assert_not_called()

    def test_noops_if_notice_already_shown(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"first_run_notice_shown": True}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            import click

            with patch.object(click, "echo") as mock_echo:
                telemetry.show_first_run_notice_if_needed()
                mock_echo.assert_not_called()

    def test_shows_notice_when_config_exists_without_flag(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "pre-existing"}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            import click

            with patch.object(click, "echo", wraps=click.echo) as mock_echo:
                telemetry.show_first_run_notice_if_needed()
                mock_echo.assert_called()
                _, kwargs = mock_echo.call_args
                assert kwargs.get("err") is True

            config = json.loads(config_path.read_text())
            assert config["first_run_notice_shown"] is True
            assert config["anonymous_id"] == "pre-existing"


class TestSetEnabled:
    def test_writes_enabled_true(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.set_enabled(True)
            config = json.loads(config_path.read_text())
            assert config["enabled"] is True

    def test_writes_enabled_false(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.set_enabled(False)
            config = json.loads(config_path.read_text())
            assert config["enabled"] is False

    def test_creates_config_if_missing(self, tmp_path):
        config_path = tmp_path / "sub" / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.set_enabled(False)
            assert config_path.exists()


class TestTelemetryCommands:
    def test_telemetry_on(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:on"])
            assert result.exit_code == 0
            assert "enabled" in result.output.lower()
            config = json.loads(config_path.read_text())
            assert config["enabled"] is True

    def test_telemetry_off(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:off"])
            assert result.exit_code == 0
            assert "disabled" in result.output.lower()
            config = json.loads(config_path.read_text())
            assert config["enabled"] is False

    def test_telemetry_status(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"enabled": True, "anonymous_id": "abc-123"}))
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            result = runner.invoke(cli, ["telemetry:status"])
            assert result.exit_code == 0
            assert "enabled" in result.output.lower()
            assert "abc-123" in result.output
            assert str(config_path) in result.output


class TestConfigPath:
    def test_default_path(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove XDG_CONFIG_HOME if set
            env = os.environ.copy()
            env.pop("XDG_CONFIG_HOME", None)
            with patch.dict(os.environ, env, clear=True):
                path = telemetry.get_config_path()
                assert path == Path.home() / ".config" / "posthog" / "hogli_telemetry.json"

    def test_xdg_config_home_respected(self, tmp_path):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(tmp_path)}):
            path = telemetry.get_config_path()
            assert path == tmp_path / "posthog" / "hogli_telemetry.json"

    def test_directory_created_if_missing(self, tmp_path):
        config_path = tmp_path / "a" / "b" / "config.json"
        with patch.object(telemetry, "get_config_path", return_value=config_path):
            telemetry.set_enabled(True)
            assert config_path.parent.exists()
