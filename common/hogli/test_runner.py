"""Auto-detecting test runner for hogli.

Detects the test type from a file path and dispatches to the correct runner
(pytest, Jest, Playwright, cargo test, go test) with appropriate options.
"""

from __future__ import annotations

import json
import shlex
import tomllib
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import click
from hogli.core.cli import cli
from hogli.core.command_types import _run
from hogli.core.manifest import REPO_ROOT

_PYTHON_ROOTS = ("posthog/", "ee/", "products/", "common/", "dags/")


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file for any supported language."""
    name = PurePosixPath(path).name
    if path.endswith(".py"):
        return name.startswith("test_") or (name.startswith("eval_") and path.startswith("ee/hogai/eval/"))
    if path.endswith((".test.ts", ".test.tsx")):
        return True
    if path.endswith(".spec.ts") and path.startswith("playwright/"):
        return True
    if path.endswith("_test.go"):
        return True
    if path.endswith("_test.rs") or ("/tests/" in path and path.endswith(".rs")):
        return True
    return False


@dataclass
class TestRunConfig:
    """Result of test type detection."""

    test_type: str
    command: list[str]
    description: str
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None


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

    If file_path points to a directory, starts the search there.
    If it points to a file, starts from its parent directory.
    Stops at REPO_ROOT to avoid escaping the repo.
    """
    repo_root = REPO_ROOT.resolve()
    path = Path(file_path)
    if path.is_absolute():
        abs_path = path.resolve()
    else:
        abs_path = (repo_root / path).resolve()
    try:
        abs_path.relative_to(repo_root)
    except ValueError:
        return None

    current = abs_path if abs_path.is_dir() else abs_path.parent
    while True:
        candidate = current / target_filename
        if candidate.exists():
            return candidate
        if current == repo_root or current.parent == current:
            break
        current = current.parent

    return None


def _parse_cargo_package_name(cargo_toml: Path) -> str | None:
    """Extract the package name from a Cargo.toml [package] section."""
    try:
        data = tomllib.loads(cargo_toml.read_text())
        return data.get("package", {}).get("name")
    except (tomllib.TOMLDecodeError, OSError):
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
    while parent == REPO_ROOT or REPO_ROOT in parent.parents:
        candidate = parent / "Cargo.toml"
        if candidate.exists() and "[workspace]" in candidate.read_text():
            workspace_toml = candidate
            break
        if parent == parent.parent:
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

    Accepts any .go file, go.mod, or directory. Runs ``go test`` from the
    module root directory (where go.mod lives) so Go can resolve packages.
    """
    go_mod = _find_nearest(file_only, "go.mod")
    if not go_mod:
        raise click.UsageError(f"No go.mod found for: {file_only}")

    mod_root = go_mod.parent
    mod_root_rel = str(mod_root.relative_to(REPO_ROOT))

    # Compute the test target relative to the module root
    abs_path = REPO_ROOT / file_only
    if abs_path.is_dir():
        try:
            pkg_rel = str(abs_path.relative_to(mod_root))
            target = f"./{pkg_rel}/..." if pkg_rel != "." else "./..."
        except ValueError:
            target = "./..."
    elif PurePosixPath(file_only).name == "go.mod":
        target = "./..."
    else:
        # Single file — run tests in its package directory
        try:
            pkg_rel = str(abs_path.parent.relative_to(mod_root))
            target = f"./{pkg_rel}/..." if pkg_rel != "." else "./..."
        except ValueError:
            target = "./..."

    return TestRunConfig(
        test_type="go",
        command=["go", "test", target],
        cwd=mod_root,
        description=f"Go test (in {mod_root_rel}, go test {target})",
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
        command=["pnpm", f"--filter={pkg_name}", "exec", "jest", file_path],
        description=f"Jest test (via {pkg_name})",
    )


def _detect_directory(dir_path: str) -> TestRunConfig:
    """Detect test type for a directory and run all tests in it."""
    # Go: directory contains or is under a go.mod
    if _find_nearest(dir_path, "go.mod"):
        return _detect_go_test(dir_path)

    # Rust: directory contains or is under a Cargo.toml
    if _find_nearest(dir_path, "Cargo.toml"):
        return _detect_rust_test(dir_path)

    # Product root: use Turbo pipeline (only for top-level product dirs)
    if dir_path.startswith("products/"):
        parts = PurePosixPath(dir_path.rstrip("/")).parts
        if len(parts) == 2:
            product_name = parts[1]
            pkg_json = REPO_ROOT / "products" / product_name / "package.json"
            if pkg_json.exists():
                pkg_name = _parse_package_json_name(pkg_json)
                if pkg_name:
                    return TestRunConfig(
                        test_type="turbo",
                        command=["pnpm", "turbo", "run", "backend:test", f"--filter={pkg_name}"],
                        description=f"Product tests via Turbo ({pkg_name})",
                    )

    # Playwright: directory is under playwright/
    if dir_path.startswith("playwright/") or dir_path == "playwright":
        return TestRunConfig(
            test_type="playwright",
            command=["pnpm", "exec", "playwright", "test", dir_path],
            description="Playwright E2E tests",
        )

    # Python: directory is under a known Python root
    if any(dir_path.startswith(root) or dir_path == root.rstrip("/") for root in _PYTHON_ROOTS):
        return TestRunConfig(
            test_type="python",
            command=["pytest", "-s", dir_path],
            description="Python tests (pytest)",
            env=_python_env(),
        )

    # Jest: directory has a package.json nearby
    if _find_nearest(dir_path, "package.json"):
        return _detect_jest_test(dir_path, dir_path)

    raise click.UsageError(
        f"Could not detect test type for directory: {dir_path}\n\n"
        "Supported: Python, Jest, Playwright, Rust, Go, Product (Turbo) directories"
    )


def detect_test_type(file_path: str) -> TestRunConfig:
    """Detect the test type from a file or directory path and return run configuration.

    Accepts files, directories, and pytest node IDs (path::Class::method).
    Rules are evaluated in priority order; first match wins.
    """
    file_only = file_path.split("::")[0] if "::" in file_path else file_path
    abs_path = REPO_ROOT / file_only

    # Directory: detect type from context
    if abs_path.is_dir():
        return _detect_directory(file_only)

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
            command=["pytest", "-c", "ee/hogai/eval/pytest.ini", "-s", file_path],
            description="Python eval test (pytest with eval config)",
            env=_python_env(),
        )

    # 3. Python tests
    if ext == ".py" and any(file_only.startswith(root) for root in _PYTHON_ROOTS):
        return TestRunConfig(
            test_type="python",
            command=["pytest", "-s", file_path],
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
        "  Files:       *.py, *.test.ts(x), *.spec.ts, *.rs, *.go, go.mod\n"
        "  Directories: any directory under a supported test root\n"
        "  Node IDs:    path/to/test.py::TestClass::test_method"
    )


# ---------------------------------------------------------------------------
# --changed: find test files changed on the current branch and run them
# ---------------------------------------------------------------------------


def _parse_porcelain_path(line: str) -> str:
    """Extract the file path from a ``git status --porcelain`` line.

    Handles renames/copies (``R  old -> new``) by taking the destination,
    and strips quotes that git adds for paths with special characters.
    """
    raw = line[3:]
    # Renames/copies: "old -> new" — take the destination
    if " -> " in raw:
        raw = raw.split(" -> ", 1)[1]
    # Git quotes paths containing special chars
    return raw.strip().strip('"')


def _get_changed_files() -> list[str]:
    """Get files changed on the current branch vs master, plus uncommitted changes."""
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if branch == "master":
        raise click.UsageError("Cannot use --changed on the master branch.")

    # Files changed between master and HEAD
    diff_vs_master = (
        subprocess.run(
            ["git", "diff", "--name-only", "master...HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )

    # Uncommitted / staged changes
    porcelain = (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        .stdout.strip()
        .splitlines()
    )
    uncommitted = [_parse_porcelain_path(line) for line in porcelain if len(line) > 3]

    return sorted(set(diff_vs_master + uncommitted))


def _run_changed(extra_args: list[str]) -> None:
    """Find changed test files, group by type, and run each group."""
    changed = _get_changed_files()
    test_files = [f for f in changed if _is_test_file(f)]

    if not test_files:
        click.secho("No changed test files found on this branch.", fg="yellow")
        raise SystemExit(0)

    click.secho(f"Found {len(test_files)} changed test file(s):", fg="cyan")
    for f in test_files:
        click.echo(f"  {f}")
    click.echo()

    # Group by test type and run each group
    groups: dict[str, list[str]] = {}
    for f in test_files:
        try:
            config = detect_test_type(f)
            groups.setdefault(config.test_type, []).append(f)
        except click.UsageError:
            click.secho(f"  Skipping (unknown type): {f}", fg="yellow")

    for test_type, files in groups.items():
        if test_type in ("python", "python-eval"):
            # pytest can take multiple files at once
            config = detect_test_type(files[0])
            command = config.command[:-1] + files  # replace last arg (single file) with all files
            click.secho(f"Running {len(files)} Python test file(s)...", fg="cyan")
            _run(command + extra_args, env=config.env if config.env else None, cwd=config.cwd)
        elif test_type == "jest":
            # Sub-group by package so each pnpm --filter is correct
            by_package: dict[str, tuple[TestRunConfig, list[str]]] = {}
            for f in files:
                cfg = detect_test_type(f)
                pkg = cfg.command[1]  # e.g. "--filter=@posthog/frontend"
                if pkg not in by_package:
                    by_package[pkg] = (cfg, [])
                by_package[pkg][1].append(f)
            for pkg, (cfg, pkg_files) in by_package.items():
                command = cfg.command[:-1] + pkg_files
                click.secho(f"Running {len(pkg_files)} Jest test file(s) ({pkg})...", fg="cyan")
                _run(command + extra_args, env=cfg.env if cfg.env else None, cwd=cfg.cwd)
        else:
            # Other types: run individually
            for f in files:
                config = detect_test_type(f)
                click.secho(f"Running: {f}", fg="cyan")
                _run(config.command + extra_args, env=config.env if config.env else None, cwd=config.cwd)


# ---------------------------------------------------------------------------
# --watch: re-run tests on file changes
# ---------------------------------------------------------------------------


def _run_watch(file_path: str, extra_args: list[str]) -> None:
    """Run tests in watch mode, re-executing on file changes."""
    resolved = _resolve_to_repo_relative(file_path)
    config = detect_test_type(resolved)

    if config.test_type in ("python", "python-eval"):
        # Use nodemon for Python, matching bin/tests behavior
        watch_dirs = ["./posthog", "./common/hogvm/python", "./ee", "./dags", "./products"]

        # Build the inner command as a properly shell-escaped string for nodemon --exec
        inner_parts = list(config.command) + list(extra_args)
        env_prefix_parts = [f"{k}={shlex.quote(v)}" for k, v in config.env.items()] if config.env else []
        inner_cmd = " ".join(env_prefix_parts + [shlex.quote(arg) for arg in inner_parts])

        # Build nodemon as a list to avoid shell=True
        nodemon_cmd: list[str] = ["nodemon"]
        for d in watch_dirs:
            nodemon_cmd.extend(["-w", d])
        nodemon_cmd.extend(["--ext", "py", "--exec", inner_cmd])

        click.secho(f"Watching: {config.description}", fg="cyan")
        _run(nodemon_cmd)

    elif config.test_type == "jest":
        # Jest has built-in --watch
        click.secho(f"Watching: {config.description}", fg="cyan")
        _run([*config.command, "--watch", *extra_args], env=config.env if config.env else None, cwd=config.cwd)

    else:
        raise click.UsageError(
            f"Watch mode is not supported for {config.test_type} tests.\n"
            "Supported: Python (nodemon) and Jest (--watch)."
        )


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


@cli.command(
    name="test",
    help=(
        "Auto-detect test type and run the correct test runner.\n\n"
        "Accepts files, directories, and pytest node IDs. Detects Python "
        "(pytest), Jest, Playwright, Rust (cargo test), Go (go test), and "
        "product directories (Turbo) based on file extension or directory context.\n\n"
        "Extra arguments are passed through to the underlying test runner.\n\n"
        "Examples:\n\n"
        "\b\n"
        "  hogli test posthog/api/test/\n"
        "  hogli test posthog/api/test/test_user.py\n"
        "  hogli test posthog/api/test/test_user.py::TestUser::test_create\n"
        "  hogli test posthog/api/test/test_user.py --watch\n"
        "  hogli test --changed\n"
        "  hogli test livestream/\n"
        "  hogli test products/visual_review/"
    ),
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("file_path", required=False, type=click.Path())
@click.option("--changed", is_flag=True, help="Run tests for files changed on the current branch")
@click.option("--watch", is_flag=True, help="Re-run tests on file changes (Python and Jest)")
@click.pass_context
def test_command(ctx: click.Context, file_path: str | None, changed: bool, watch: bool) -> None:
    """Auto-detect test type and run the correct test runner."""
    if changed:
        if file_path:
            raise click.UsageError("Cannot combine --changed with a file path.")
        if watch:
            raise click.UsageError("Cannot combine --changed with --watch.")
        _run_changed(list(ctx.args))
        return

    if not file_path:
        raise click.UsageError(
            "Missing argument FILE_PATH.\n\nUsage: hogli test [OPTIONS] FILE_PATH\n       hogli test --changed"
        )

    if watch:
        _run_watch(file_path, list(ctx.args))
        return

    resolved = _resolve_to_repo_relative(file_path)
    config = detect_test_type(resolved)

    click.secho(f"Detected: {config.description}", fg="cyan")
    _run(config.command + list(ctx.args), env=config.env if config.env else None, cwd=config.cwd)
