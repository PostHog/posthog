"""Tests for auto-detecting test runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import patch

import click
from hogli.test_runner import _resolve_to_repo_relative, detect_test_type
from parameterized import parameterized


class TestDetectTestType:
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

    @parameterized.expand(
        [
            (
                "frontend/src/scenes/dashboard/Dashboard.test.tsx",
                "frontend-jest",
                ["pnpm", "--filter=@posthog/frontend", "jest", "frontend/src/scenes/dashboard/Dashboard.test.tsx"],
            ),
            (
                "frontend/src/lib/utils.test.ts",
                "frontend-jest",
                ["pnpm", "--filter=@posthog/frontend", "jest", "frontend/src/lib/utils.test.ts"],
            ),
            (
                "products/alerts/frontend/alerts.test.tsx",
                "frontend-jest",
                ["pnpm", "--filter=@posthog/frontend", "jest", "products/alerts/frontend/alerts.test.tsx"],
            ),
        ]
    )
    def test_frontend_jest(self, file_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == expected_type
        assert config.command == expected_command

    def test_nodejs_jest(self) -> None:
        config = detect_test_type("nodejs/tests/cdp/cdp-api.test.ts")
        assert config.test_type == "nodejs-jest"
        assert config.command == [
            "pnpm",
            "--filter=@posthog/nodejs",
            "jest",
            "nodejs/tests/cdp/cdp-api.test.ts",
        ]

    def test_playwright(self) -> None:
        config = detect_test_type("playwright/e2e/dashboards.spec.ts")
        assert config.test_type == "playwright"
        assert config.command == ["pnpm", "exec", "playwright", "test", "playwright/e2e/dashboards.spec.ts"]

    @parameterized.expand(
        [
            (
                "common/hogvm/typescript/src/__tests__/execute.test.ts",
                "common-jest",
                "@posthog/hogvm",
            ),
            (
                "common/replay-shared/src/replay.test.ts",
                "common-jest",
                "@posthog/replay-shared",
            ),
            (
                "common/replay-headless/src/render.test.ts",
                "common-jest",
                "@posthog/replay-headless",
            ),
        ]
    )
    def test_common_jest_packages(self, file_path: str, expected_type: str, expected_filter: str) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == expected_type
        assert f"--filter={expected_filter}" in config.command

    @patch("hogli.test_runner._find_cargo_package", return_value="capture")
    def test_rust_workspace_crate(self, _mock_find: object) -> None:
        config = detect_test_type("rust/capture/tests/events.rs")
        assert config.test_type == "rust"
        assert config.command == ["cargo", "test", "--manifest-path=rust/Cargo.toml", "-p", "capture"]

    @patch("hogli.test_runner._find_cargo_package", return_value="posthog-cli")
    def test_rust_standalone_cli(self, _mock_find: object) -> None:
        config = detect_test_type("cli/src/main_test.rs")
        assert config.test_type == "rust"
        assert config.command == ["cargo", "test", "--manifest-path=cli/Cargo.toml", "-p", "posthog-cli"]

    @patch("hogli.test_runner._find_cargo_package", return_value="funnels")
    def test_rust_standalone_funnel_udf(self, _mock_find: object) -> None:
        config = detect_test_type("funnel-udf/src/lib_test.rs")
        assert config.test_type == "rust"
        assert config.command == ["cargo", "test", "--manifest-path=funnel-udf/Cargo.toml", "-p", "funnels"]

    @patch("hogli.test_runner._find_cargo_package", return_value=None)
    def test_rust_without_package_name(self, _mock_find: object) -> None:
        config = detect_test_type("rust/capture/tests/events.rs")
        assert config.test_type == "rust"
        assert config.command == ["cargo", "test", "--manifest-path=rust/Cargo.toml"]
        assert "-p" not in config.command

    def test_rust_unknown_location_raises(self) -> None:
        with pytest.raises(click.UsageError, match="not in a known crate directory"):
            detect_test_type("random/thing.rs")

    @parameterized.expand(
        [
            ("livestream/main_test.go", "go", ["go", "test", "./livestream/..."]),
            ("livestream/handlers/handler_test.go", "go", ["go", "test", "./livestream/handlers/..."]),
            ("tools/phrocs/internal/tui/app_test.go", "go", ["go", "test", "./tools/phrocs/internal/tui/..."]),
            (
                "bin/hobby-installer/installer_test.go",
                "go",
                ["go", "test", "./bin/hobby-installer/..."],
            ),
        ]
    )
    def test_go_tests(self, file_path: str, expected_type: str, expected_command: list[str]) -> None:
        config = detect_test_type(file_path)
        assert config.test_type == expected_type
        assert config.command == expected_command

    def test_go_unknown_module_raises(self) -> None:
        with pytest.raises(click.UsageError, match="not in a known module"):
            detect_test_type("random/foo_test.go")

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
        # When cwd is repo root, relative paths stay as-is
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
