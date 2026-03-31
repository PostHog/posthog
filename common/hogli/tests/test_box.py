"""Tests for the hogli box commands."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from click.testing import CliRunner
from hogli.box import (
    cli as box_cli,
    coder,
)
from hogli.core.cli import cli

runner = CliRunner()


class TestCoderConfig:
    """Test config and runtime preflight helpers."""

    @pytest.mark.parametrize(
        "env_key, env_value, expected_url",
        [
            ("HOGLI_BOX_CODER_URL", "https://env.example.com", "https://env.example.com"),
            ("CODER_URL", "https://coder-env.example.com", "https://coder-env.example.com"),
        ],
    )
    def test_get_coder_url_prefers_env_over_manifest(
        self,
        monkeypatch: pytest.MonkeyPatch,
        env_key: str,
        env_value: str,
        expected_url: str,
    ) -> None:
        monkeypatch.delenv("HOGLI_BOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)
        monkeypatch.setenv(env_key, env_value)

        with patch("hogli.box.coder.load_manifest", return_value={"metadata": {"box": {"coder_url": "ignored"}}}):
            assert coder.get_coder_url() == expected_url

    def test_get_coder_url_falls_back_to_manifest_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_BOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)

        with patch(
            "hogli.box.coder.load_manifest",
            return_value={"metadata": {"box": {"coder_url": "https://manifest.example.com"}}},
        ):
            assert coder.get_coder_url() == "https://manifest.example.com"

    def test_runtime_ready_requires_setup_when_coder_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "ensure_tailscale_connected", lambda setup_hint=coder.RUNTIME_SETUP_HINT: None)
        monkeypatch.setattr(coder, "coder_installed", lambda: False)

        with pytest.raises(SystemExit):
            coder.ensure_runtime_ready()

        assert "Run `hogli box:setup`." in capsys.readouterr().out


class TestBoxCommands:
    """Test the Click command contract for box commands."""

    def test_box_help_lists_setup_and_runtime_commands(self) -> None:
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "box:setup" in result.output
        assert "box:open" in result.output
        assert "box:logs" in result.output

    def test_plain_box_command_lists_available_workspace_commands(self) -> None:
        result = runner.invoke(cli, ["box"])

        assert result.exit_code == 0
        assert "hogli box:setup" in result.output
        assert "hogli box:start" in result.output
        assert "hogli box:destroy" in result.output

    def test_box_setup_runs_explicit_setup_steps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(box_cli, "ensure_tailscale_connected", lambda setup_hint="": calls.append("tailscale"))
        monkeypatch.setattr(box_cli, "ensure_coder_installed", lambda: calls.append("install"))
        monkeypatch.setattr(box_cli, "ensure_coder_authenticated", lambda: calls.append("login"))
        monkeypatch.setattr(
            box_cli,
            "maybe_configure_ssh",
            lambda configure_ssh: calls.append(f"ssh:{configure_ssh}"),
        )
        monkeypatch.setattr(box_cli, "print_setup_summary", lambda: calls.append("summary"))

        result = runner.invoke(cli, ["box:setup", "--skip-configure-ssh"])

        assert result.exit_code == 0
        assert calls == ["tailscale", "install", "login", "ssh:False", "summary"]

    def test_box_status_does_not_reference_missing_box_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "get_workspace_name", lambda: "devbox-raul")
        monkeypatch.setattr(
            box_cli,
            "get_workspace",
            lambda name: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )

        result = runner.invoke(cli, ["box:status"])

        assert result.exit_code == 0
        assert "box:update" not in result.output
        assert "Recreate the workspace" in result.output
