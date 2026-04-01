"""Tests for the hogli devbox commands."""

from __future__ import annotations

import json
import errno
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from hogli.core.cli import cli
from hogli.devbox import (
    cli as devbox_cli,
    coder,
    config as devbox_config,
)

runner = CliRunner()


@pytest.fixture
def devbox_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "hogli_devbox.json"
    monkeypatch.setattr(devbox_config, "get_config_path", lambda: config_path)
    return config_path


class TestDevboxConfig:
    """Test persisted devbox preferences."""

    def test_save_git_identity_persists_trimmed_values(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity(" PostHog Engineer ", " test-user@example.com ")

        assert devbox_config.load_config() == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }
        assert json.loads(devbox_config_path.read_text()) == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
        }


class TestCoderConfig:
    """Test config and runtime preflight helpers."""

    @pytest.mark.parametrize(
        "env_key, env_value, expected_url",
        [
            ("HOGLI_DEVBOX_CODER_URL", "https://env.example.com", "https://env.example.com"),
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
        monkeypatch.delenv("HOGLI_DEVBOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)
        monkeypatch.setenv(env_key, env_value)

        with patch("hogli.devbox.coder.load_manifest", return_value={"metadata": {"devbox": {"coder_url": "ignored"}}}):
            assert coder.get_coder_url() == expected_url

    def test_get_coder_url_falls_back_to_manifest_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CODER_URL", raising=False)
        monkeypatch.delenv("CODER_URL", raising=False)

        with patch(
            "hogli.devbox.coder.load_manifest",
            return_value={"metadata": {"devbox": {"coder_url": "https://manifest.example.com"}}},
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

        assert "Run `hogli devbox:setup`." in capsys.readouterr().out

    def test_run_build_raises_if_stdout_pipe_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.subprocess, "Popen", lambda *args, **kwargs: MagicMock(stdout=None))

        with pytest.raises(RuntimeError, match="stdout pipe was not opened"):
            coder._run_build(["coder", "start", "devbox-test-user"])


class TestWorkspaceNaming:
    """Test workspace name derivation, label validation, and extraction."""

    def test_default_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name() == "devbox-test-user"

    def test_labeled_workspace_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name("api") == "devbox-test-user-api"

    def test_multi_segment_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.get_workspace_name("my-project") == "devbox-test-user-my-project"

    @pytest.mark.parametrize("bad_label", ["", "UPPER", "has space", "-leading", "trailing-"])
    def test_invalid_label_rejected(self, monkeypatch: pytest.MonkeyPatch, bad_label: str) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        with pytest.raises(SystemExit):
            coder.get_workspace_name(bad_label)

    def test_extract_label_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("devbox-test-user") is None

    def test_extract_label_named(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("devbox-test-user-api") == "api"

    def test_extract_label_hyphenated_username(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user-two")
        assert coder.extract_workspace_label("devbox-test-user-two") is None
        assert coder.extract_workspace_label("devbox-test-user-two-api") == "api"

    def test_extract_label_unrelated_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "get_username", lambda: "test-user")
        assert coder.extract_workspace_label("other-workspace") is None


class TestWorkspaceCreation:
    """Test Coder workspace creation parameter passing."""

    def test_create_workspace_passes_git_identity_as_rich_parameters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["args"] = args
            captured["parameters"] = parameters
            captured["verbose"] = verbose
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace(
            "devbox-test-user",
            50,
            claude_oauth_token="oauth-token",
            git_name="PostHog Engineer",
            git_email="test-user@example.com",
            verbose=True,
        )

        assert captured == {
            "args": ["coder", "create", "devbox-test-user", "--template", "posthog-linux", "--yes"],
            "parameters": {
                "disk_size": "50",
                "repo": "https://github.com/PostHog/posthog",
                "claude_oauth_token": "oauth-token",
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
            },
            "verbose": True,
        }


class TestResolveWorkspaceName:
    """Test the CLI workspace resolution logic."""

    def test_explicit_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace_name",
            lambda label=None: f"devbox-test-user-{label}" if label else "devbox-test-user",
        )
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        assert devbox_cli.resolve_workspace_name("api") == "devbox-test-user-api"

    def test_no_workspaces_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        assert devbox_cli.resolve_workspace_name(None) == "devbox-test-user"

    def test_single_workspace_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [{"name": "devbox-test-user-api"}])
        assert devbox_cli.resolve_workspace_name(None) == "devbox-test-user-api"

    def test_multiple_workspaces_prefers_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-api"}],
        )
        assert devbox_cli.resolve_workspace_name(None) == "devbox-test-user"

    def test_multiple_workspaces_no_default_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(
            devbox_cli, "extract_workspace_label", lambda name: name.split("-", 2)[-1] if name.count("-") > 1 else None
        )
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user-api"}, {"name": "devbox-test-user-web"}],
        )
        with pytest.raises(SystemExit):
            devbox_cli.resolve_workspace_name(None)


class TestDevboxCommands:
    """Test the Click command contract for devbox commands."""

    def test_devbox_help_lists_setup_and_runtime_commands(self) -> None:
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "devbox:setup" in result.output
        assert "devbox:open" in result.output
        assert "devbox:logs" in result.output

    def test_plain_devbox_command_lists_available_workspace_commands(self) -> None:
        result = runner.invoke(cli, ["devbox"])

        assert result.exit_code == 0
        assert "hogli devbox:setup" in result.output
        assert "hogli devbox:start" in result.output
        assert "hogli devbox:list" in result.output
        assert "hogli devbox:destroy" in result.output

    def test_devbox_setup_runs_explicit_setup_steps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": calls.append("tailscale"))
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda: calls.append("install"))
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: calls.append("login"))
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_ssh",
            lambda configure_ssh: calls.append(f"ssh:{configure_ssh}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_git_identity",
            lambda configure_git_identity: calls.append(f"git:{configure_git_identity}"),
        )
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: calls.append("summary"))

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-ssh", "--skip-configure-git-identity"])

        assert result.exit_code == 0
        assert calls == ["tailscale", "install", "login", "ssh:False", "git:False", "summary"]

    def test_devbox_setup_uses_coder_profile_as_prompt_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
    ) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)
        monkeypatch.setattr(devbox_cli, "get_default_git_identity", lambda: ("Coder User", "coder@example.com"))

        # No Y/n gate -- prompts shown directly with coder profile defaults
        result = runner.invoke(
            cli,
            ["devbox:setup", "--skip-configure-ssh"],
            input="\n\n",
        )

        assert result.exit_code == 0
        assert "Saved Git identity for new workspaces: Coder User <coder@example.com>" in result.output
        assert json.loads(devbox_config_path.read_text()) == {
            "git_name": "Coder User",
            "git_email": "coder@example.com",
        }

    def test_devbox_setup_skips_git_identity_when_already_saved(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
    ) -> None:
        devbox_config_path.write_text(json.dumps({"git_name": "Existing User", "git_email": "existing@example.com"}))

        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh: None)
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: None)

        result = runner.invoke(cli, ["devbox:setup", "--skip-configure-ssh"])

        assert result.exit_code == 0
        assert "Using saved Git identity: Existing User <existing@example.com>" in result.output

    def test_devbox_start_creates_workspace_with_default_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: "devbox-test-user")
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(
            devbox_cli,
            "_maybe_prompt_for_claude_oauth_token",
            lambda configure_claude: "oauth-token",
        )
        monkeypatch.setattr(
            devbox_cli,
            "create_workspace",
            lambda name,
            disk_size,
            claude_oauth_token=None,
            git_name=None,
            git_email=None,
            verbose=False: captured.update(
                {
                    "name": name,
                    "disk_size": str(disk_size),
                    "claude_oauth_token": claude_oauth_token,
                    "git_name": git_name,
                    "git_email": git_email,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0
        assert captured == {
            "name": "devbox-test-user",
            "disk_size": "50",
            "claude_oauth_token": "oauth-token",
            "git_name": None,
            "git_email": None,
        }

    def test_devbox_start_with_name_creates_labeled_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "resolve_workspace_name",
            lambda label: f"devbox-test-user-{label}" if label else "devbox-test-user",
        )
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: "api")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {"git_name": "PostHog Engineer", "git_email": "test-user@example.com"},
        )
        monkeypatch.setattr(
            devbox_cli,
            "_maybe_prompt_for_claude_oauth_token",
            lambda configure_claude: None,
        )
        monkeypatch.setattr(
            devbox_cli,
            "create_workspace",
            lambda name,
            disk_size,
            claude_oauth_token=None,
            git_name=None,
            git_email=None,
            verbose=False: captured.update(
                {
                    "name": name,
                    "git_name": git_name,
                    "git_email": git_email,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start", "--name", "api"])

        assert result.exit_code == 0
        assert captured["name"] == "devbox-test-user-api"
        assert captured["git_name"] == "PostHog Engineer"
        assert captured["git_email"] == "test-user@example.com"
        assert "--name api" in result.output

    def test_claude_prompt_uses_fallback_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_OAUTH_TOKEN", "oauth-token")

        assert devbox_cli._maybe_prompt_for_claude_oauth_token(None) == "oauth-token"

    def test_local_port_check_ignores_missing_ipv6_support(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ipv4_socket = MagicMock()
        ipv4_socket.__enter__.return_value = ipv4_socket

        ipv6_socket = MagicMock()
        ipv6_socket.__enter__.return_value = ipv6_socket
        ipv6_socket.bind.side_effect = OSError(errno.EAFNOSUPPORT, "Address family not supported")

        sockets = iter([ipv4_socket, ipv6_socket])
        monkeypatch.setattr(devbox_cli.socket, "socket", lambda *args, **kwargs: next(sockets))

        assert devbox_cli._local_port_is_available(8010) is True

    def test_devbox_status_does_not_reference_missing_devbox_update(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: "devbox-test-user")
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["devbox:status"])

        assert result.exit_code == 0
        assert "devbox:update" not in result.output
        assert "Recreate the workspace" in result.output

    def test_devbox_forward_forwards_when_local_port_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: "devbox-test-user")
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: True)
        monkeypatch.setattr(
            devbox_cli,
            "port_forward_replace",
            lambda name, local_port, remote_port: captured.update(
                {"name": name, "local_port": local_port, "remote_port": remote_port}
            ),
        )

        result = runner.invoke(cli, ["devbox:forward"])

        assert result.exit_code == 0
        assert "Forwarding devbox-test-user:8010 -> localhost:8010" in result.output
        assert captured == {"name": "devbox-test-user", "local_port": 8010, "remote_port": 8010}

    def test_devbox_forward_fails_early_when_local_port_is_in_use(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: "devbox-test-user")
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: False)

        result = runner.invoke(cli, ["devbox:forward", "--port", "8010"])

        assert result.exit_code == 1
        assert "Local port 8010 is already in use." in result.output
        assert "hogli devbox:forward --port 8011" in result.output


class TestStartExistingWorkspace:
    """Test git identity sync when starting an existing workspace."""

    def test_syncs_git_identity_before_starting_stopped_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        captured_params: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {"git_name": "PostHog Engineer", "git_email": "test-user@example.com"},
        )

        def fake_update(name: str, params: dict[str, str]) -> None:
            calls.append("update_params")
            captured_params.update({"name": name, "params": params})

        monkeypatch.setattr(devbox_cli, "update_workspace_parameters", fake_update)
        monkeypatch.setattr(
            devbox_cli,
            "start_workspace",
            lambda name, verbose=False: calls.append("start"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "stopped"}}, verbose=False)

        assert calls == ["update_params", "start"]
        assert captured_params == {
            "name": "devbox-test-user",
            "params": {"git_name": "PostHog Engineer", "git_email": "test-user@example.com"},
        }

    def test_skips_sync_when_no_git_identity_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {})
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: calls.append("update_params"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "start_workspace",
            lambda name, verbose=False: calls.append("start"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "stopped"}}, verbose=False)

        assert calls == ["start"]

    def test_skips_sync_for_running_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "running")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {"git_name": "PostHog Engineer", "git_email": "test-user@example.com"},
        )
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace_parameters",
            lambda name, params: calls.append("update_params"),
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        devbox_cli._start_existing_workspace("devbox-test-user", {"latest_build": {"status": "running"}}, verbose=False)

        assert calls == []


class TestDevboxList:
    """Test the devbox:list command."""

    def test_devbox_list_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "No devboxes found" in result.output

    def test_devbox_list_shows_workspaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: "api" if "api" in name else None)
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [
                {"name": "devbox-test-user", "latest_build": {"status": "running"}},
                {"name": "devbox-test-user-api", "latest_build": {"status": "stopped"}},
            ],
        )

        result = runner.invoke(cli, ["devbox:list"])

        assert result.exit_code == 0
        assert "(default)" in result.output
        assert "api" in result.output
        assert "devbox-test-user-api" in result.output
