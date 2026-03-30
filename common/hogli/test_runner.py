"""Auto-detecting test runner for hogli.

Detects the test type from a file path and dispatches to the correct runner
(pytest, Jest, Playwright, cargo test, go test) with appropriate options.
"""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import click
from hogli.core.cli import cli
from hogli.core.command_types import _run
from hogli.core.manifest import REPO_ROOT

_PYTHON_ROOTS = ("posthog/", "ee/", "products/", "common/", "dags/")


@dataclass
class TestRunConfig:
    """Result of test type detection."""

    test_type: str
    command: list[str]
    description: str
    env: dict[str, str] = field(default_factory=dict)


def _python_env() -> dict[str, str]:
    """Environment variables needed for Python test runs."""
    env: dict[str, str] = {"REDIS_URL": "redis:///"}
    if platform.system() == "Darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    return env


def _resolve_to_repo_relative(file_path: str) -> str:
    """Convert absolute or relative path to repo-relative path.

    Handles pytest node IDs (path::Class::method) by only resolving
    the file path portion, then reattaching the node ID.
    """
    node_id_suffix = ""
    if "::" in file_path:
        parts = file_path.split("::", 1)
        file_path = parts[0]
        node_id_suffix = "::" + parts[1]

    path = Path(file_path)
    if path.is_absolute():
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:
            return str(path) + node_id_suffix
        return str(rel) + node_id_suffix

    # Relative path: resolve from cwd then make repo-relative
    resolved = Path.cwd() / path
    try:
        rel = resolved.relative_to(REPO_ROOT)
        return str(rel) + node_id_suffix
    except ValueError:
        return file_path + node_id_suffix


def _find_nearest(file_path: str, target_filename: str) -> Path | None:
    """Walk upward from file_path to find the nearest file with target_filename.

    Stops at REPO_ROOT to avoid escaping the repo.
    """
    current = (REPO_ROOT / file_path).parent
    while True:
        candidate = current / target_filename
        if candidate.exists():
            return candidate
        if current == REPO_ROOT:
            break
        current = current.parent
    return None


def _parse_cargo_package_name(cargo_toml: Path) -> str | None:
    """Extract the package name from a Cargo.toml [package] section."""
    in_package = False
    for line in cargo_toml.read_text().splitlines():
        stripped = line.strip()
        if stripped == "[package]":
            in_package = True
        elif stripped.startswith("[") and in_package:
            break
        elif in_package and stripped.startswith("name"):
            _, _, value = stripped.partition("=")
            return value.strip().strip('"').strip("'")
    return None


def _parse_package_json_name(package_json: Path) -> str | None:
    """Extract the name field from a package.json."""
    try:
        data = json.loads(package_json.read_text())
        return data.get("name")
    except (json.JSONDecodeError, OSError):
        return None


def _detect_rust_test(file_only: str) -> TestRunConfig:
    """Detect Rust test configuration by finding the nearest Cargo.toml.

    If the nearest Cargo.toml is a crate inside a workspace, uses the workspace
    root manifest with ``-p <package>`` to target the specific crate.
    """
    crate_toml = _find_nearest(file_only, "Cargo.toml")
    if not crate_toml:
        raise click.UsageError(f"No Cargo.toml found for: {file_only}")

    package_name = _parse_cargo_package_name(crate_toml)

    # Check if there's a parent workspace Cargo.toml above this one
    workspace_toml = None
    parent = crate_toml.parent.parent
    while parent >= REPO_ROOT:
        candidate = parent / "Cargo.toml"
        if candidate.exists() and "[workspace]" in candidate.read_text():
            workspace_toml = candidate
            break
        if parent == REPO_ROOT:
            break
        parent = parent.parent

    if workspace_toml:
        manifest_path = str(workspace_toml.relative_to(REPO_ROOT))
        command = ["cargo", "test", f"--manifest-path={manifest_path}"]
        if package_name:
            command.extend(["-p", package_name])
        desc = f"Rust test (cargo test -p {package_name})" if package_name else "Rust test (cargo test)"
    else:
        manifest_path = str(crate_toml.relative_to(REPO_ROOT))
        command = ["cargo", "test", f"--manifest-path={manifest_path}"]
        desc = "Rust test (cargo test)"

    return TestRunConfig(test_type="rust", command=command, description=desc)


def _detect_go_test(file_only: str) -> TestRunConfig:
    """Detect Go test configuration by finding the nearest go.mod.

    Accepts any .go file or go.mod and runs tests from the module root.
    """
    go_mod = _find_nearest(file_only, "go.mod")
    if not go_mod:
        raise click.UsageError(f"No go.mod found for: {file_only}")

    mod_root = str(go_mod.parent.relative_to(REPO_ROOT))

    return TestRunConfig(
        test_type="go",
        command=["go", "test", f"./{mod_root}/..."],
        description=f"Go test (go test ./{mod_root}/...)",
    )


def _detect_jest_test(file_only: str, file_path: str) -> TestRunConfig:
    """Detect Jest test configuration by finding the nearest package.json."""
    package_json = _find_nearest(file_only, "package.json")
    if not package_json:
        raise click.UsageError(f"No package.json found for: {file_path}")

    pkg_name = _parse_package_json_name(package_json)
    if not pkg_name:
        raise click.UsageError(f"No name field in {package_json.relative_to(REPO_ROOT)}")

    return TestRunConfig(
        test_type="jest",
        command=["pnpm", f"--filter={pkg_name}", "jest", file_path],
        description=f"Jest test (via {pkg_name})",
    )


def detect_test_type(file_path: str) -> TestRunConfig:
    """Detect the test type from a file path and return run configuration.

    Rules are evaluated in priority order; first match wins.
    """
    file_only = file_path.split("::")[0] if "::" in file_path else file_path
    parts = PurePosixPath(file_only).parts
    ext = PurePosixPath(file_only).suffix

    # 1. Playwright E2E tests
    if len(parts) > 0 and parts[0] == "playwright" and file_only.endswith(".spec.ts"):
        return TestRunConfig(
            test_type="playwright",
            command=["pnpm", "exec", "playwright", "test", file_path],
            description="Playwright E2E test",
        )

    # 2. Python eval tests (special pytest config)
    if file_only.startswith("ee/hogai/eval/") and ext == ".py":
        return TestRunConfig(
            test_type="python-eval",
            command=["pytest", "-c", "ee/hogai/eval/pytest.ini", file_path],
            description="Python eval test (pytest with eval config)",
            env=_python_env(),
        )

    # 3. Python tests
    if ext == ".py" and any(file_only.startswith(root) for root in _PYTHON_ROOTS):
        return TestRunConfig(
            test_type="python",
            command=["pytest", file_path],
            description="Python test (pytest)",
            env=_python_env(),
        )

    # 4. Jest tests (*.test.ts, *.test.tsx) — finds nearest package.json to determine pnpm filter
    if file_only.endswith((".test.ts", ".test.tsx")):
        return _detect_jest_test(file_only, file_path)

    # 5. Rust tests — finds nearest Cargo.toml
    if ext == ".rs":
        return _detect_rust_test(file_only)

    # 6. Go — any .go file or go.mod; finds nearest go.mod and runs from module root
    if ext == ".go" or PurePosixPath(file_only).name == "go.mod":
        return _detect_go_test(file_only)

    raise click.UsageError(
        f"Could not detect test type for: {file_path}\n\n"
        "Supported patterns:\n"
        "  Python:     **/*.py (under posthog/, ee/, products/, common/, dags/)\n"
        "  Jest:       **/*.test.ts(x) (finds nearest package.json)\n"
        "  Playwright: playwright/**/*.spec.ts\n"
        "  Rust:       **/*.rs (finds nearest Cargo.toml)\n"
        "  Go:         **/*_test.go (finds nearest go.mod)"
    )


@cli.command(
    name="test",
    help=(
        "Auto-detect test type and run the correct test runner.\n\n"
        "Detects Python (pytest), Jest, Playwright, Rust (cargo test), and\n"
        "Go (go test) based on the file path. For Jest, Rust, and Go it finds\n"
        "the nearest package.json, Cargo.toml, or go.mod automatically.\n\n"
        "Extra arguments are passed through to the underlying test runner.\n\n"
        "Examples:\n\n"
        "  hogli test posthog/api/test/test_user.py\n\n"
        "  hogli test posthog/api/test/test_user.py::TestUserAPI::test_retrieve_current_user\n\n"
        "  hogli test frontend/src/scenes/dashboard/Dashboard.test.tsx\n\n"
        "  hogli test posthog/api/test/test_user.py -v -s\n\n"
        "  hogli test playwright/e2e/dashboards.spec.ts\n\n"
        "  hogli test rust/capture/tests/events.rs\n\n"
        "  hogli test livestream/main_test.go"
    ),
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("file_path")
@click.pass_context
def test_command(ctx: click.Context, file_path: str) -> None:
    """Auto-detect test type and run the correct test runner."""
    resolved = _resolve_to_repo_relative(file_path)
    config = detect_test_type(resolved)

    click.secho(f"Detected: {config.description}", fg="cyan")
    _run(config.command + list(ctx.args), env=config.env if config.env else None)
