"""Tests for auto-detecting test runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import patch

import click
from hogli.test_runner import _resolve_to_repo_relative, detect_test_type
from parameterized import parameterized


class TestDetectTestType:
    """Tests hit real files on disk — they validate that detection works
    end-to-end against the actual repo layout (package.json, Cargo.toml, go.mod).
    """

    @parameterized.expand(
        [
            ("posthog/api/test/test_user.py", "python", ["pytest", "posthog/api/test/test_user.py"]),
            ("posthog/models/test/test_team.py", "python", ["pytest", "posthog/models/test/test_team.py"]),
            ("ee/clickhouse/test/test_client.py", "python", ["pytest", "ee/clickhouse/test/test_client.py"]),
            (
                "products/alerts/backend/test/test_api.py",
                "python",
                ["pytest", "products/alerts/backend/test/test_api.py"],
            ),
            ("common/hogli/tests/test_cli.py", "python", ["pytest", "common/hogli/tests/test_cli.py"]),
            ("dags/tests/test_dag.py", "python", ["pytest", "dags/tests/test_dag.py"]),
        ]
    )
    def test_python_tests(self, file_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == expected_type
        assert config.command == expected_command
        assert "REDIS_URL" in config.env

    def test_python_with_node_id(self) -> None:
        config = detect_test_type("posthog/api/test/test_user.py::TestUserAPI::test_retrieve")
        assert config.test_type == "python"
        assert config.command == ["pytest", "posthog/api/test/test_user.py::TestUserAPI::test_retrieve"]

    def test_python_eval_uses_special_config(self) -> None:
        config = detect_test_type("ee/hogai/eval/eval_router.py")
        assert config.test_type == "python-eval"
        assert config.command == ["pytest", "-c", "ee/hogai/eval/pytest.ini", "ee/hogai/eval/eval_router.py"]
        assert "REDIS_URL" in config.env

    # -- Jest tests: these hit real package.json files on disk --

    @parameterized.expand(
        [
            ("frontend/src/scenes/dashboard/Dashboard.test.tsx", "@posthog/frontend"),
            ("frontend/src/lib/utils.test.ts", "@posthog/frontend"),
        ]
    )
    def test_frontend_jest(self, file_path: str, expected_filter: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "jest"
        assert config.command == ["pnpm", f"--filter={expected_filter}", "jest", file_path]

    def test_nodejs_jest(self) -> None:
        config = detect_test_type("nodejs/tests/cdp/cdp-api.test.ts")
        assert config.test_type == "jest"
        assert "--filter=@posthog/nodejs" in config.command

    @parameterized.expand(
        [
            ("common/hogvm/typescript/src/__tests__/execute.test.ts", "@posthog/hogvm"),
            ("common/replay-shared/src/replay.test.ts", "@posthog/replay-shared"),
            ("common/replay-headless/src/render.test.ts", "@posthog/replay-headless"),
        ]
    )
    def test_common_jest_packages(self, file_path: str, expected_filter: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "jest"
        assert f"--filter={expected_filter}" in config.command

    def test_playwright(self) -> None:
        config = detect_test_type("playwright/e2e/dashboards.spec.ts")
        assert config.test_type == "playwright"
        assert config.command == ["pnpm", "exec", "playwright", "test", "playwright/e2e/dashboards.spec.ts"]

    # -- Rust tests: these hit real Cargo.toml files on disk --

    def test_rust_workspace_crate(self) -> None:
        config = detect_test_type("rust/capture/tests/events.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=rust/Cargo.toml" in config.command
        assert "-p" in config.command
        assert "capture" in config.command

    def test_rust_standalone_cli(self) -> None:
        config = detect_test_type("cli/src/main.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=cli/Cargo.toml" in config.command

    def test_rust_standalone_funnel_udf(self) -> None:
        config = detect_test_type("funnel-udf/src/lib.rs")
        assert config.test_type == "rust"
        assert "--manifest-path=funnel-udf/Cargo.toml" in config.command

    def test_rust_no_cargo_toml_raises(self) -> None:
        with pytest.raises(click.UsageError, match="No Cargo.toml found"):
            detect_test_type("random/thing.rs")

    # -- Go tests: these hit real go.mod files on disk --
    # Any .go file or go.mod should run tests from the module root

    @parameterized.expand(
        [
            ("livestream/main_test.go", ["go", "test", "./livestream/..."]),
            ("livestream/main.go", ["go", "test", "./livestream/..."]),
            ("livestream/handlers/handler.go", ["go", "test", "./livestream/..."]),
            ("livestream/go.mod", ["go", "test", "./livestream/..."]),
            ("tools/phrocs/internal/tui/app_test.go", ["go", "test", "./tools/phrocs/..."]),
            ("bin/hobby-installer/installer_test.go", ["go", "test", "./bin/hobby-installer/..."]),
        ]
    )
    def test_go_tests(self, file_path: str, expected_command: list[str]) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == "go"
        assert config.command == expected_command

    def test_go_no_go_mod_raises(self) -> None:
        with pytest.raises(click.UsageError, match="No go.mod found"):
            detect_test_type("random/foo_test.go")

    # -- Directory tests: run all tests in a directory --

    @parameterized.expand(
        [
            ("posthog/api/test", "python", ["pytest", "posthog/api/test"]),
            ("ee/hogai", "python", ["pytest", "ee/hogai"]),
            ("common/hogli/tests", "python", ["pytest", "common/hogli/tests"]),
        ]
    )
    def test_python_directory(self, dir_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(dir_path)
        assert config.test_type == expected_type
        assert config.command == expected_command

    def test_go_directory(self) -> None:
        config = detect_test_type("livestream")
        assert config.test_type == "go"
        assert config.command == ["go", "test", "./livestream/..."]

    def test_rust_directory(self) -> None:
        config = detect_test_type("rust/capture/tests")
        assert config.test_type == "rust"
        assert "--manifest-path=rust/Cargo.toml" in config.command

    def test_jest_directory(self) -> None:
        config = detect_test_type("frontend/src/scenes/dashboard")
        assert config.test_type == "jest"
        assert "--filter=@posthog/frontend" in config.command

    def test_playwright_directory(self) -> None:
        config = detect_test_type("playwright/e2e")
        assert config.test_type == "playwright"
        assert config.command == ["pnpm", "exec", "playwright", "test", "playwright/e2e"]

    # -- Edge cases --

    def test_unknown_file_raises(self) -> None:
        with pytest.raises(click.UsageError, match="Could not detect test type"):
            detect_test_type("random/file.txt")

    def test_unknown_python_location_raises(self) -> None:
        with pytest.raises(click.UsageError, match="Could not detect test type"):
            detect_test_type("somewhere/test_foo.py")

    @patch("hogli.test_runner.platform")
    def test_macos_env_var(self, mock_platform) -> None:
        mock_platform.system.return_value = "Darwin"
        config = detect_test_type("posthog/api/test/test_user.py")
        assert config.env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] == "YES"

    @patch("hogli.test_runner.platform")
    def test_linux_no_objc_env_var(self, mock_platform) -> None:
        mock_platform.system.return_value = "Linux"
        config = detect_test_type("posthog/api/test/test_user.py")
        assert "OBJC_DISABLE_INITIALIZE_FORK_SAFETY" not in config.env


class TestResolveToRepoRelative:
    def test_relative_path_unchanged(self) -> None:
        with patch("hogli.test_runner.Path.cwd", return_value=Path(str(_get_repo_root()))):
            result = _resolve_to_repo_relative("posthog/api/test/test_user.py")
            assert result == "posthog/api/test/test_user.py"

    def test_absolute_path_made_relative(self) -> None:
        repo_root = str(_get_repo_root())
        result = _resolve_to_repo_relative(f"{repo_root}/posthog/api/test/test_user.py")
        assert result == "posthog/api/test/test_user.py"

    def test_node_id_preserved(self) -> None:
        repo_root = str(_get_repo_root())
        result = _resolve_to_repo_relative(f"{repo_root}/posthog/test_foo.py::TestBar::test_baz")
        assert result == "posthog/test_foo.py::TestBar::test_baz"

    def test_relative_with_node_id(self) -> None:
        with patch("hogli.test_runner.Path.cwd", return_value=Path(str(_get_repo_root()))):
            result = _resolve_to_repo_relative("posthog/test_foo.py::TestBar")
            assert result == "posthog/test_foo.py::TestBar"


def _get_repo_root():
    from hogli.core.manifest import REPO_ROOT

    return REPO_ROOT
