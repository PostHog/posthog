"""Auto-detecting test runner for hogli.

Detects the test type from a file path and dispatches to the correct runner
(pytest, Jest, Playwright, cargo test, go test) with appropriate options.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import click
from hogli.core.cli import cli
from hogli.core.command_types import _run
from hogli.core.manifest import REPO_ROOT

# Known common TS packages with jest configs
_COMMON_JS_PACKAGES: dict[str, str] = {
    "common/hogvm/typescript": "@posthog/hogvm",
    "common/replay-shared": "@posthog/replay-shared",
    "common/replay-headless": "@posthog/replay-headless",
}

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


def _find_cargo_package(file_path: str) -> str | None:
    """Walk upward from file_path to find the nearest Cargo.toml and return its package name."""
    path = REPO_ROOT / file_path
    for parent in path.parents:
        cargo_toml = parent / "Cargo.toml"
        if cargo_toml.exists():
            # Quick parse: look for name = "..." in [package] section
            in_package = False
            for line in cargo_toml.read_text().splitlines():
                stripped = line.strip()
                if stripped == "[package]":
                    in_package = True
                elif stripped.startswith("[") and in_package:
                    break
                elif in_package and stripped.startswith("name"):
                    # name = "foo"
                    _, _, value = stripped.partition("=")
                    return value.strip().strip('"').strip("'")
            return None
        if parent == REPO_ROOT:
            break
    return None


def _detect_rust_test(file_only: str, file_path: str) -> TestRunConfig:
    """Detect Rust test configuration."""
    # Determine the cargo manifest directory
    if file_only.startswith("rust/"):
        # Inside the rust/ workspace — use workspace root and target the specific package
        manifest_dir = "rust"
    elif file_only.startswith("cli/"):
        manifest_dir = "cli"
    elif file_only.startswith("funnel-udf/"):
        manifest_dir = "funnel-udf"
    else:
        raise click.UsageError(
            f"Rust file not in a known crate directory: {file_path}\nExpected rust/**, cli/**, or funnel-udf/**"
        )

    package_name = _find_cargo_package(file_only)
    command = ["cargo", "test", f"--manifest-path={manifest_dir}/Cargo.toml"]
    if package_name:
        command.extend(["-p", package_name])

    desc = f"Rust test (cargo test -p {package_name})" if package_name else "Rust test (cargo test)"
    return TestRunConfig(test_type="rust", command=command, description=desc)


def _detect_go_test(file_only: str) -> TestRunConfig:
    """Detect Go test configuration."""
    # Find the Go module root by locating the nearest go.mod
    path = PurePosixPath(file_only)
    # The Go module roots in this repo
    go_modules = ["livestream", "tools/phrocs", "bin/hobby-installer"]

    for mod_root in go_modules:
        if file_only.startswith(mod_root + "/"):
            # Get the package directory (dir containing the test file)
            pkg_dir = str(path.parent)
            return TestRunConfig(
                test_type="go",
                command=["go", "test", f"./{pkg_dir}/..."],
                description=f"Go test (go test in {mod_root})",
            )

    raise click.UsageError(
        f"Go test file not in a known module: {file_only}\n"
        "Expected livestream/**, tools/phrocs/**, or bin/hobby-installer/**"
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

    # 4. Node.js (plugin server) tests
    if len(parts) > 0 and parts[0] == "nodejs" and file_only.endswith(".test.ts"):
        return TestRunConfig(
            test_type="nodejs-jest",
            command=["pnpm", "--filter=@posthog/nodejs", "jest", file_path],
            description="Node.js test (Jest via @posthog/nodejs)",
        )

    # 5. Common TS package tests
    for pkg_path, pkg_name in _COMMON_JS_PACKAGES.items():
        if file_only.startswith(pkg_path + "/") and (file_only.endswith(".test.ts") or file_only.endswith(".test.tsx")):
            return TestRunConfig(
                test_type="common-jest",
                command=["pnpm", f"--filter={pkg_name}", "jest", file_path],
                description=f"Common package test (Jest via {pkg_name})",
            )

    # 6. Frontend Jest tests (includes products/*/frontend/)
    is_frontend_test = file_only.endswith((".test.ts", ".test.tsx"))
    is_frontend_path = file_only.startswith("frontend/src/") or (
        file_only.startswith("products/") and "/frontend/" in file_only
    )
    if is_frontend_test and is_frontend_path:
        return TestRunConfig(
            test_type="frontend-jest",
            command=["pnpm", "--filter=@posthog/frontend", "jest", file_path],
            description="Frontend test (Jest via @posthog/frontend)",
        )

    # 7. Rust tests (cargo workspace at rust/, plus standalone cli/ and funnel-udf/)
    if ext == ".rs":
        return _detect_rust_test(file_only, file_path)

    # 8. Go tests
    if file_only.endswith("_test.go"):
        return _detect_go_test(file_only)

    raise click.UsageError(
        f"Could not detect test type for: {file_path}\n\n"
        "Supported patterns:\n"
        "  Python:     posthog/**/test_*.py, ee/**/test_*.py, products/*/backend/**/test_*.py\n"
        "  Frontend:   frontend/src/**/*.test.ts(x), products/*/frontend/**/*.test.ts(x)\n"
        "  Node.js:    nodejs/**/*.test.ts\n"
        "  Playwright: playwright/**/*.spec.ts\n"
        "  Common:     common/hogvm/typescript/**/*.test.ts, common/replay-*/**/*.test.ts\n"
        "  Rust:       rust/**/*.rs, cli/**/*.rs, funnel-udf/**/*.rs\n"
        "  Go:         livestream/**/*_test.go, tools/phrocs/**/*_test.go"
    )


@cli.command(
    name="test",
    help=(
        "Auto-detect test type and run the correct test runner.\n\n"
        "Detects Python (pytest), Frontend Jest, Node.js Jest, Playwright,\n"
        "Rust (cargo test), Go (go test), and common package tests based on the\n"
        "file path.\n\n"
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
