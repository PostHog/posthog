"""Tests for the hogli devbox commands."""

from __future__ import annotations

import json
import errno
import subprocess
from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
from hogli.core.cli import cli
from hogli.devbox import (
    cli as devbox_cli,
    coder,
    config as devbox_config,
    keychain,
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

    def test_save_dotfiles_uri_persists_trimmed_value(self, devbox_config_path: Path) -> None:
        devbox_config.save_dotfiles_uri(" https://github.com/user/dotfiles ")

        config = devbox_config.load_config()
        assert config["dotfiles_uri"] == "https://github.com/user/dotfiles"

    def test_save_dotfiles_uri_merges_with_existing_config(self, devbox_config_path: Path) -> None:
        devbox_config.save_git_identity("PostHog Engineer", "test-user@example.com")
        devbox_config.save_dotfiles_uri("https://github.com/user/dotfiles")

        config = devbox_config.load_config()
        assert config == {
            "git_name": "PostHog Engineer",
            "git_email": "test-user@example.com",
            "dotfiles_uri": "https://github.com/user/dotfiles",
        }


class TestResolveTailscale:
    """Test Tailscale CLI resolution with macOS app bundle fallback."""

    def test_prefers_path_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: "/usr/local/bin/tailscale")
        assert coder._resolve_tailscale() == "/usr/local/bin/tailscale"

    def test_falls_back_to_macos_app_bundle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "darwin")
        monkeypatch.setattr(coder.os.path, "isfile", lambda path: path == coder._MACOS_TAILSCALE_CLI)
        assert coder._resolve_tailscale() == coder._MACOS_TAILSCALE_CLI

    def test_returns_none_when_not_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "darwin")
        monkeypatch.setattr(coder.os.path, "isfile", lambda path: False)
        assert coder._resolve_tailscale() is None

    def test_skips_macos_path_on_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(coder.sys, "platform", "linux")
        assert coder._resolve_tailscale() is None

    def test_tailscale_env_sets_cli_flag_for_app_bundle(self) -> None:
        env = coder._tailscale_env(coder._MACOS_TAILSCALE_CLI)
        assert env is not None
        assert env["TAILSCALE_BE_CLI"] == "1"

    def test_tailscale_env_returns_none_for_path_binary(self) -> None:
        assert coder._tailscale_env("/usr/local/bin/tailscale") is None

    def test_tailscale_status_uses_resolved_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: coder._MACOS_TAILSCALE_CLI)

        captured_args: list[list[str]] = []
        captured_env: list[object] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured_args.append(args)
            captured_env.append(kwargs.get("env"))
            return subprocess.CompletedProcess(args, 0, '{"BackendState": "Running"}', "")

        monkeypatch.setattr(coder.subprocess, "run", fake_run)

        status = coder._tailscale_status()

        assert status == {"BackendState": "Running"}
        assert captured_args[0][0] == coder._MACOS_TAILSCALE_CLI
        env = captured_env[0]
        assert isinstance(env, dict)
        assert env["TAILSCALE_BE_CLI"] == "1"

    def test_ensure_tailscale_connected_says_not_installed_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(coder, "tailscale_connected", lambda: False)
        monkeypatch.setattr(coder, "_resolve_tailscale", lambda: None)

        with pytest.raises(SystemExit):
            coder.ensure_tailscale_connected()

        assert "not installed" in capsys.readouterr().out


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
                **coder._TEMPLATE_PARAMETER_DEFAULTS,
                "disk_size": "50",
                "repo": "https://github.com/PostHog/posthog",
                "claude_oauth_token": "oauth-token",
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
            },
            "verbose": True,
        }

    def test_create_workspace_passes_dotfiles_uri_as_rich_parameter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, dict[str, str]] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["parameters"] = parameters
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace(
            "devbox-test-user",
            100,
            dotfiles_uri="https://github.com/user/dotfiles",
            verbose=True,
        )

        assert captured["parameters"]["dotfiles_uri"] == "https://github.com/user/dotfiles"

    def test_create_workspace_includes_template_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, dict[str, str]] = {}

        def fake_run_with_rich_parameters(
            args: list[str], parameters: dict[str, str], *, verbose: bool | None = None
        ) -> subprocess.CompletedProcess[str]:
            captured["parameters"] = parameters
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(coder, "_run_with_rich_parameters", fake_run_with_rich_parameters)

        coder.create_workspace("devbox-test-user", 100, verbose=True)

        for key, value in coder._TEMPLATE_PARAMETER_DEFAULTS.items():
            assert captured["parameters"][key] == value


class TestResolveWorkspaceName:
    """Test the CLI workspace resolution logic."""

    def test_explicit_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace_name",
            lambda label=None: f"devbox-test-user-{label}" if label else "devbox-test-user",
        )
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        name, workspaces = devbox_cli.resolve_workspace_name("api")
        assert name == "devbox-test-user-api"
        assert workspaces == []

    def test_no_workspaces_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [])
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"
        assert workspaces == []

    def test_single_workspace_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "list_user_workspaces", lambda: [{"name": "devbox-test-user-api"}])
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user-api"
        assert len(workspaces) == 1

    def test_multiple_workspaces_prefers_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "get_workspace_name", lambda label=None: "devbox-test-user")
        monkeypatch.setattr(
            devbox_cli,
            "list_user_workspaces",
            lambda: [{"name": "devbox-test-user"}, {"name": "devbox-test-user-api"}],
        )
        name, workspaces = devbox_cli.resolve_workspace_name(None)
        assert name == "devbox-test-user"
        assert len(workspaces) == 2

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
        assert "hogli devbox:restart" in result.output
        assert "hogli devbox:update" in result.output
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
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_dotfiles",
            lambda configure_dotfiles: calls.append(f"dotfiles:{configure_dotfiles}"),
        )
        monkeypatch.setattr(
            devbox_cli,
            "maybe_configure_claude_token",
            lambda configure_claude: calls.append(f"claude:{configure_claude}"),
        )
        monkeypatch.setattr(devbox_cli, "print_setup_summary", lambda: calls.append("summary"))

        result = runner.invoke(
            cli,
            [
                "devbox:setup",
                "--skip-configure-ssh",
                "--skip-configure-git-identity",
                "--skip-configure-dotfiles",
                "--skip-configure-claude",
            ],
        )

        assert result.exit_code == 0
        assert calls == [
            "tailscale",
            "install",
            "login",
            "ssh:False",
            "git:False",
            "dotfiles:False",
            "claude:False",
            "summary",
        ]

    def test_devbox_setup_uses_coder_profile_as_prompt_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
        devbox_config_path: Path,
    ) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_tailscale_connected", lambda setup_hint="": None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_installed", lambda: None)
        monkeypatch.setattr(devbox_cli, "ensure_coder_authenticated", lambda: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_ssh", lambda configure_ssh: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_token", lambda configure_claude: None)
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
        monkeypatch.setattr(devbox_cli, "maybe_configure_dotfiles", lambda configure_dotfiles: None)
        monkeypatch.setattr(devbox_cli, "maybe_configure_claude_token", lambda configure_claude: None)
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
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
            dotfiles_uri=None,
            verbose=False: captured.update(
                {
                    "name": name,
                    "disk_size": str(disk_size),
                    "claude_oauth_token": claude_oauth_token,
                    "git_name": git_name,
                    "git_email": git_email,
                    "dotfiles_uri": dotfiles_uri,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start"])

        assert result.exit_code == 0
        assert captured == {
            "name": "devbox-test-user",
            "disk_size": "100",
            "claude_oauth_token": "oauth-token",
            "git_name": None,
            "git_email": None,
            "dotfiles_uri": None,
        }

    def test_devbox_start_with_name_creates_labeled_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, str | None] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(
            devbox_cli,
            "resolve_workspace_name",
            lambda label: (f"devbox-test-user-{label}" if label else "devbox-test-user", []),
        )
        monkeypatch.setattr(devbox_cli, "get_workspace", lambda name, workspaces=None: None)
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: "api")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
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
            dotfiles_uri=None,
            verbose=False: captured.update(
                {
                    "name": name,
                    "git_name": git_name,
                    "git_email": git_email,
                    "dotfiles_uri": dotfiles_uri,
                }
            ),
        )

        result = runner.invoke(cli, ["devbox:start", "--name", "api"])

        assert result.exit_code == 0
        assert captured["name"] == "devbox-test-user-api"
        assert captured["git_name"] == "PostHog Engineer"
        assert captured["git_email"] == "test-user@example.com"
        assert captured["dotfiles_uri"] == "https://github.com/user/dotfiles"
        assert "--name api" in result.output

    def test_devbox_restart_calls_restart_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(
            devbox_cli,
            "restart_workspace",
            lambda name, verbose=False: captured.update({"name": name, "verbose": verbose}),
        )

        result = runner.invoke(cli, ["devbox:restart"])

        assert result.exit_code == 0
        assert "Restarting" in result.output
        assert captured["name"] == "devbox-test-user"

    def test_devbox_update_applies_when_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "outdated": True, "latest_build": {"status": "running"}},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)
        monkeypatch.setattr(devbox_cli, "load_config", lambda: {"dotfiles_uri": "https://github.com/user/dotfiles"})
        monkeypatch.setattr(
            devbox_cli,
            "update_workspace",
            lambda name, parameters=None, verbose=False: captured.update({"name": name, "parameters": parameters}),
        )

        result = runner.invoke(cli, ["devbox:update"])

        assert result.exit_code == 0
        assert "Updating" in result.output
        assert captured["name"] == "devbox-test-user"
        assert captured["parameters"] == {"dotfiles_uri": "https://github.com/user/dotfiles"}

    def test_devbox_update_skips_when_up_to_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"name": name, "outdated": False, "latest_build": {"status": "running"}},
        )

        result = runner.invoke(cli, ["devbox:update"])

        assert result.exit_code == 0
        assert "already up to date" in result.output

    def test_claude_prompt_uses_fallback_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_OAUTH_TOKEN", "oauth-token")
        monkeypatch.setattr(keychain, "read", lambda service: None)

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

    def test_devbox_status_shows_update_hint_when_outdated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(
            devbox_cli,
            "get_workspace",
            lambda name, workspaces=None: {"latest_build": {"status": "running", "resources": []}, "outdated": True},
        )
        monkeypatch.setattr(devbox_cli, "extract_workspace_label", lambda name: None)

        result = runner.invoke(cli, ["devbox:status"])

        assert result.exit_code == 0
        assert "devbox:update" in result.output

    def test_devbox_forward_forwards_when_local_port_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "ensure_runtime_ready", lambda: None)
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
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
        monkeypatch.setattr(devbox_cli, "resolve_workspace_name", lambda label: ("devbox-test-user", []))
        monkeypatch.setattr(devbox_cli, "_local_port_is_available", lambda port: False)

        result = runner.invoke(cli, ["devbox:forward", "--port", "8010"])

        assert result.exit_code == 1
        assert "Local port 8010 is already in use." in result.output
        assert "hogli devbox:forward --port 8011" in result.output


class TestStartExistingWorkspace:
    """Test workspace parameter sync when starting an existing workspace."""

    def test_syncs_workspace_parameters_before_starting_stopped_workspace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        captured_params: dict[str, object] = {}

        monkeypatch.setattr(devbox_cli, "get_workspace_status", lambda ws: "stopped")
        monkeypatch.setattr(
            devbox_cli,
            "load_config",
            lambda: {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
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
            "params": {
                "git_name": "PostHog Engineer",
                "git_email": "test-user@example.com",
                "dotfiles_uri": "https://github.com/user/dotfiles",
            },
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


class TestKeychain:
    """Test macOS Keychain helpers."""

    @pytest.mark.parametrize(
        "fn,args,expected",
        [
            (keychain.read, ("test-service",), None),
            (keychain.write, ("test-service", "value"), False),
            (keychain.delete, ("test-service",), False),
        ],
    )
    def test_operations_return_sentinel_on_non_macos(self, monkeypatch: pytest.MonkeyPatch, fn, args, expected) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: False)
        assert fn(*args) == expected

    def test_is_supported_reflects_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        assert keychain.is_supported() is True
        monkeypatch.setattr(keychain, "_is_macos", lambda: False)
        assert keychain.is_supported() is False

    def test_read_returns_value_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        monkeypatch.setattr(
            keychain.subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="my-token\n", stderr=""),
        )
        assert keychain.read("test-service") == "my-token"

    def test_read_returns_none_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        monkeypatch.setattr(
            keychain.subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 44, stdout="", stderr=""),
        )
        assert keychain.read("test-service") is None

    def test_write_calls_delete_then_add(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(keychain.subprocess, "run", fake_run)
        assert keychain.write("test-service", "my-value") is True
        assert len(calls) == 2
        assert "delete-generic-password" in calls[0]
        assert "test-service" in calls[0]
        assert "add-generic-password" in calls[1]
        assert "my-value" in calls[1]

    def test_delete_returns_true_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        monkeypatch.setattr(
            keychain.subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
        )
        assert keychain.delete("test-service") is True

    def test_delete_returns_false_when_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "_is_macos", lambda: True)
        monkeypatch.setattr(
            keychain.subprocess,
            "run",
            lambda args, **kwargs: subprocess.CompletedProcess(args, 44, "", ""),
        )
        assert keychain.delete("test-service") is False


class TestClaudeTokenResolution:
    """Test the token resolution order in _maybe_prompt_for_claude_oauth_token."""

    def test_env_var_wins_over_keychain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setenv("CLAUDE_OAUTH_TOKEN", "env-token")
        monkeypatch.setattr(keychain, "read", lambda service: "keychain-token")

        assert devbox_cli._maybe_prompt_for_claude_oauth_token(None) == "env-token"

    def test_keychain_used_when_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(keychain, "read", lambda service: "keychain-token")

        assert devbox_cli._maybe_prompt_for_claude_oauth_token(None) == "keychain-token"

    def test_interactive_prompt_saves_to_keychain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(keychain, "read", lambda service: None)
        saved: list[str] = []

        def fake_write(service: str, value: str) -> bool:
            saved.append(value)
            return True

        monkeypatch.setattr(keychain, "write", fake_write)

        monkeypatch.setattr(click, "confirm", lambda *a, **kw: True)
        monkeypatch.setattr(click, "prompt", lambda *a, **kw: "my-pasted-token")
        token = devbox_cli._maybe_prompt_for_claude_oauth_token(None)

        assert token == "my-pasted-token"
        assert saved == ["my-pasted-token"]

    def test_explicit_configure_claude_skips_keychain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(keychain, "read", lambda service: "stale-token")
        saved: list[str] = []

        def fake_write(service: str, value: str) -> bool:
            saved.append(value)
            return True

        monkeypatch.setattr(keychain, "write", fake_write)

        monkeypatch.setattr(click, "prompt", lambda *a, **kw: "fresh-token")
        token = devbox_cli._maybe_prompt_for_claude_oauth_token(True)

        assert token == "fresh-token"
        assert saved == ["fresh-token"]

    def test_skipping_claude_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOGLI_DEVBOX_CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(keychain, "read", lambda service: None)

        assert devbox_cli._maybe_prompt_for_claude_oauth_token(False) is None


class TestSetupClaudeToken:
    """Test the Claude token step in devbox:setup."""

    def test_skips_when_token_already_in_keychain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "read", lambda service: "existing-token")
        monkeypatch.setattr(keychain, "is_supported", lambda: True)

        from io import StringIO

        output = StringIO()
        monkeypatch.setattr("sys.stdout", output)
        devbox_cli.maybe_configure_claude_token(None)
        assert "configured" in output.getvalue()

    def test_shows_explanation_before_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "read", lambda service: None)
        monkeypatch.setattr(keychain, "is_supported", lambda: True)

        from io import StringIO

        output = StringIO()
        monkeypatch.setattr(click, "echo", lambda msg="", **kw: output.write(msg + "\n"))
        monkeypatch.setattr(click, "prompt", lambda *a, **kw: "")
        devbox_cli.maybe_configure_claude_token(None)
        text = output.getvalue()
        assert "Claude Code (optional)" in text
        assert "Keychain" in text
        assert "claude setup-token" in text

    def test_skips_on_non_macos(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "read", lambda service: None)
        monkeypatch.setattr(keychain, "is_supported", lambda: False)

        from io import StringIO

        output = StringIO()
        monkeypatch.setattr(click, "echo", lambda msg="", **kw: output.write(msg + "\n"))
        devbox_cli.maybe_configure_claude_token(None)
        assert "CLAUDE_OAUTH_TOKEN" in output.getvalue()

    def test_configure_claude_true_replaces_existing_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(keychain, "read", lambda service: "stale-token")
        monkeypatch.setattr(keychain, "is_supported", lambda: True)
        saved: list[str] = []

        def fake_write(service: str, value: str) -> bool:
            saved.append(value)
            return True

        monkeypatch.setattr(keychain, "write", fake_write)
        monkeypatch.setattr(click, "echo", lambda msg="", **kw: None)
        monkeypatch.setattr(click, "pause", lambda msg="": None)
        monkeypatch.setattr(click, "confirm", lambda *a, **kw: True)
        monkeypatch.setattr(click, "prompt", lambda *a, **kw: "fresh-token")

        devbox_cli.maybe_configure_claude_token(True)
        assert saved == ["fresh-token"]
