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


class TestWorkspaceNaming:
    """Test workspace name derivation, label validation, and extraction."""

    def test_default_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.get_workspace_name() == "devbox-raul"

    def test_labeled_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.get_workspace_name("api") == "devbox-raul-api"

    def test_multi_segment_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.get_workspace_name("my-project") == "devbox-raul-my-project"

    @pytest.mark.parametrize("bad_label", ["", "UPPER", "has space", "-leading", "trailing-"])
    def test_invalid_label_rejected(self, monkeypatch: pytest.MonkeyPatch, bad_label: str) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        with pytest.raises(SystemExit):
            coder.get_workspace_name(bad_label)

    def test_extract_label_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.extract_workspace_label("devbox-raul") is None

    def test_extract_label_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.extract_workspace_label("devbox-raul-api") == "api"

    def test_extract_label_hyphenated_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "jean-luc")
        assert coder.extract_workspace_label("devbox-jean-luc") is None
        assert coder.extract_workspace_label("devbox-jean-luc-api") == "api"

    def test_extract_label_unrelated_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "raul")
        assert coder.extract_workspace_label("other-workspace") is None


class TestResolveWorkspaceName:
    """Test the CLI workspace resolution logic."""

    def test_explicit_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            box_cli, "get_workspace_name", lambda label=None: f"devbox-raul-{label}" if label else "devbox-raul"
        )
        monkeypatch.setattr(box_cli, "list_user_workspaces", lambda: [])
        assert box_cli.resolve_workspace_name("api") == "devbox-raul-api"

    def test_no_workspaces_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "get_workspace_name", lambda label=None: "devbox-raul")
        monkeypatch.setattr(box_cli, "list_user_workspaces", lambda: [])
        assert box_cli.resolve_workspace_name(None) == "devbox-raul"

    def test_single_workspace_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "list_user_workspaces", lambda: [{"name": "devbox-raul-api"}])
        assert box_cli.resolve_workspace_name(None) == "devbox-raul-api"

    def test_multiple_workspaces_prefers_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "get_workspace_name", lambda label=None: "devbox-raul")
        monkeypatch.setattr(
            box_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-raul"}, {"name": "devbox-raul-api"}],
        )
        assert box_cli.resolve_workspace_name(None) == "devbox-raul"

    def test_multiple_workspaces_no_default_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "get_workspace_name", lambda label=None: "devbox-raul")
        monkeypatch.setattr(
            box_cli, "extract_workspace_label", lambda name: name.split("-", 2)[-1] if name.count("-") > 1 else None
        )
        monkeypatch.setattr(
            box_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-raul-api"}, {"name": "devbox-raul-web"}],
        )
        with pytest.raises(SystemExit):
            box_cli.resolve_workspace_name(None)


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
        assert "hogli box:list" in result.output
        assert "hogli box:claude" in result.output
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

    def test_box_start_creates_workspace_with_default_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "get_workspace", lambda name: None)
        monkeypatch.setattr(box_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(
            box_cli,
            "_maybe_prompt_for_claude_oauth_token",
            lambda configure_claude: "oauth-token",
        )
        monkeypatch.setattr(
            box_cli,
            "create_workspace",
            lambda name, disk_size, claude_oauth_token=None, verbose=False: captured.update(
                {
                    "name": name,
                    "disk_size": str(disk_size),
                    "claude_oauth_token": claude_oauth_token,
                }
            ),
        )

        result = runner.invoke(cli, ["box:start"])

        assert result.exit_code == 0
        assert captured == {
            "name": "devbox-raul",
            "disk_size": "50",
            "claude_oauth_token": "oauth-token",
        }

    def test_box_start_with_name_creates_labeled_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            box_cli,
            "resolve_workspace_name",
            lambda label, for_create=False: f"devbox-raul-{label}" if label else "devbox-raul",
        )
        monkeypatch.setattr(box_cli, "get_workspace", lambda name: None)
        monkeypatch.setattr(box_cli, "extract_workspace_label", lambda name: "api")
        monkeypatch.setattr(
            box_cli,
            "_maybe_prompt_for_claude_oauth_token",
            lambda configure_claude: None,
        )
        monkeypatch.setattr(
            box_cli,
            "create_workspace",
            lambda name, disk_size, claude_oauth_token=None, verbose=False: captured.update({"name": name}),
        )

        result = runner.invoke(cli, ["box:start", "--name", "api"])

        assert result.exit_code == 0
        assert captured["name"] == "devbox-raul-api"
        assert "--name api" in result.output

    def test_box_status_does_not_reference_missing_box_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(
            box_cli,
            "get_workspace",
            lambda name: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )
        monkeypatch.setattr(box_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["box:status"])

        assert result.exit_code == 0
        assert "box:update" not in result.output
        assert "Recreate the workspace" in result.output

    def test_box_claude_check_reports_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "get_workspace_status", lambda workspace: "running")
        monkeypatch.setattr(box_cli, "get_workspace", lambda name: {"latest_build": {"status": "running"}})

        class Result:
            returncode = 0

        monkeypatch.setattr(box_cli, "run_in_workspace", lambda name, command, capture_output=False: Result())

        result = runner.invoke(cli, ["box:claude", "--check"])

        assert result.exit_code == 0
        assert "Claude Code is ready in the workspace." in result.output

    def test_box_claude_check_reports_missing_auth(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "get_workspace_status", lambda workspace: "running")
        monkeypatch.setattr(box_cli, "get_workspace", lambda name: {"latest_build": {"status": "running"}})

        class Result:
            returncode = 1

        monkeypatch.setattr(box_cli, "run_in_workspace", lambda name, command, capture_output=False: Result())

        result = runner.invoke(cli, ["box:claude", "--check"])

        assert result.exit_code == 1
        assert "Claude Code is not ready in the workspace." in result.output

    def test_box_claude_set_token_updates_workspace_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "get_workspace_status", lambda workspace: "running")
        monkeypatch.setattr(box_cli, "get_workspace", lambda name: {"latest_build": {"status": "running"}})
        monkeypatch.setattr(
            box_cli,
            "_maybe_prompt_for_claude_oauth_token",
            lambda configure_claude: "oauth-token",
        )
        monkeypatch.setattr(
            box_cli,
            "update_workspace_parameters",
            lambda name, parameters: captured.update({"name": name, "parameters": parameters}),
        )

        result = runner.invoke(cli, ["box:claude", "--set-token"])

        assert result.exit_code == 0
        assert captured == {"name": "devbox-raul", "parameters": {"claude_oauth_token": "oauth-token"}}

    def test_box_forward_forwards_when_local_port_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "_local_port_is_available", lambda port: True)
        monkeypatch.setattr(
            box_cli,
            "port_forward_replace",
            lambda name, local_port, remote_port: captured.update(
                {"name": name, "local_port": local_port, "remote_port": remote_port}
            ),
        )

        result = runner.invoke(cli, ["box:forward"])

        assert result.exit_code == 0
        assert "Forwarding devbox-raul:8010 -> localhost:8010" in result.output
        assert captured == {"name": "devbox-raul", "local_port": 8010, "remote_port": 8010}

    def test_box_forward_fails_early_when_local_port_is_in_use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "resolve_workspace_name", lambda label, for_create=False: "devbox-raul")
        monkeypatch.setattr(box_cli, "_local_port_is_available", lambda port: False)

        result = runner.invoke(cli, ["box:forward", "--port", "8010"])

        assert result.exit_code == 1
        assert "Local port 8010 is already in use." in result.output
        assert "hogli box:forward --port 8011" in result.output


class TestBoxList:
    """Test the box:list command."""

    def test_box_list_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "list_user_workspaces", lambda: [])

        result = runner.invoke(cli, ["box:list"])

        assert result.exit_code == 0
        assert "No devboxes found" in result.output

    def test_box_list_shows_workspaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(box_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(box_cli, "extract_workspace_label", lambda name: "api" if "api" in name else None)
        monkeypatch.setattr(
            box_cli,
            "list_user_workspaces",
            lambda: [
                {"name": "devbox-raul", "latest_build": {"status": "running"}},
                {"name": "devbox-raul-api", "latest_build": {"status": "stopped"}},
            ],
        )

        result = runner.invoke(cli, ["box:list"])

        assert result.exit_code == 0
        assert "(default)" in result.output
        assert "api" in result.output
        assert "devbox-raul-api" in result.output
