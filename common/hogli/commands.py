"""Developer Click commands for PostHog workflows.

This is the extension point for adding new Click commands to hogli.
Add your @cli.command() decorated functions here as an alternative to shell scripts.

They auto-register with hogli and appear in `hogli --help` automatically.

Example:
    ```python
    import click
    from common.hogli.core.cli import cli

    @cli.command(name="my:command", help="Does something useful")
    @click.argument('path', type=click.Path())
    @click.option('--flag', is_flag=True, help='Enable feature')
    def my_command(path, flag):
        '''Command implementation.'''
        # Your Python logic here
        click.echo(f"Processing {path}")
    ```

Guidelines:
- Use Click decorators for arguments and options
- Import cli group from common.hogli.core.cli
- Name commands with colons for grouping (e.g., 'test:python', 'db:migrate')
- Add helpful docstrings - they become the command help text
- Prefer Python Click commands over shell scripts for better type safety

For simple shell commands or bin script delegation, use manifest.yaml instead.
"""

from __future__ import annotations

import os
import time
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import click
from hogli.core.cli import cli

MAX_SAMPLE_PATHS = 8
PYTHON_CACHE_PATTERNS = ("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache")
NODE_ARTIFACT_PATTERNS = (
    ".parcel-cache",
    ".eslintcache",
    ".turbo",
    ".yalc",
    ".typegen",
    "pnpm-error.log",
    "pnpm-debug.log",
    "frontend/.cache",
    "frontend/tmp",
    "frontend/types",
    "frontend/dist",
    "frontend/storybook-static",
    "frontend/@posthog/apps-common/dist",
    "common/storybook/dist",
    "common/tailwind/dist",
    "common/plugin_transpiler/dist",
    "common/hogvm/typescript/.parcel-cache",
    "common/hogvm/typescript/dist",
    "plugin-server/dist",
    "storybook-static",
    "playwright-report",
    "playwright/playwright-report",
    "playwright/test-results",
    "test-results",
    "frontend/__snapshots__/__diff_output__",
    "frontend/__snapshots__/__failures__",
    "products/*/dist",
    "products/*/storybook-static",
)


@dataclass
class CleanupItem:
    """Single file or directory slated for cleanup."""

    path: Path
    size: float
    is_dir: bool


@dataclass
class CleanupEstimate:
    """Data describing what a cleanup category would remove."""

    total_size: float
    items: list[CleanupItem] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    available: bool = True


@dataclass
class CleanupStats:
    """Result of executing a cleanup action."""

    freed: float = 0.0
    deleted_anything: bool = False


@dataclass
class CleanupCategory:
    """Metadata and handlers for a disk cleanup category."""

    id: str
    title: str
    description: Sequence[str]
    estimate: Callable[[Path], CleanupEstimate]
    cleanup: Callable[[CleanupEstimate, Path], CleanupStats]
    confirmation_prompt: str
    default_confirm: bool = True
    include_in_total: bool = True
    skip_if_empty: bool = True
    dry_run_message: str | None = None
    post_cleanup_message: str | None = None


@dataclass
class CleanupResult:
    """Outcome of running a cleanup category (used for the summary)."""

    freed: float = 0.0
    ran_cleanup: bool = False
    deleted_anything: bool = False


@cli.command(
    name="doctor:disk",
    help="Interactive disk space cleanup for common PostHog dev bloat",
)
@click.option("--dry-run", is_flag=True, help="Show what would be cleaned without deleting")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm all cleanup operations")
@click.option(
    "--area",
    multiple=True,
    type=click.Choice(
        ["flox-logs", "docker", "python", "dagster", "node-artifacts", "rust", "node-modules"],
        case_sensitive=False,
    ),
    help="Specific cleanup area(s) to run. Can be specified multiple times. Without this, all areas run.",
)
def doctor_disk(
    dry_run: bool,
    yes: bool,
    area: tuple[str, ...],
) -> None:
    """Clean up disk space by pruning caches, build outputs, and containers.

    This command is tailored to the technologies used in the repository:
    - Flox environments (Python dependencies)
    - Docker Compose services
    - Django + pytest + mypy/ruff caches
    - Dagster background job storage
    - pnpm/Vite/Tailwind/Storybook/Playwright build artifacts
    - Rust workspaces built with Cargo
    - pnpm-managed node_modules across the workspace

    By default, runs all cleanup categories interactively. Use flags to target
    specific categories. Use --dry-run to preview what would be removed and
    --yes to skip prompts.
    """

    from hogli.core.manifest import REPO_ROOT

    click.echo("🔍 PostHog Disk Space Cleanup\n")

    if dry_run:
        click.echo("🚀 Running in DRY-RUN mode - no files will be deleted\n")

    all_categories: list[CleanupCategory] = [
        CleanupCategory(
            id="flox_logs",
            title="📁 Flox logs (.flox/log)",
            description=[
                "Remove Flox CLI logs older than 7 days from the dev environment manager.",
                "These logs can grow to 32GB+ after repeated 'flox' operations.",
            ],
            estimate=_estimate_flox_logs,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up Flox logs older than 7 days?",
            dry_run_message="Would delete Flox log files older than 7 days.",
        ),
        CleanupCategory(
            id="docker",
            title="🐳 Docker system (images, containers, volumes)",
            description=[
                "Runs 'docker system prune -a --volumes' to reclaim unused Docker resources.",
                "PostHog's docker-compose stacks rely on Docker heavily during development.",
            ],
            estimate=_estimate_docker_usage,
            cleanup=_cleanup_docker,
            confirmation_prompt="Clean up Docker system (prune unused resources)?",
            include_in_total=False,
            skip_if_empty=False,
            dry_run_message="Would run: docker system prune -a --volumes -f",
        ),
        CleanupCategory(
            id="python",
            title="🐍 Python caches (__pycache__, .mypy_cache, .pytest_cache, .ruff_cache)",
            description=[
                "Removes bytecode and analysis caches created by Django, pytest, mypy, and ruff.",
            ],
            estimate=_estimate_python_caches,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up Python caches?",
        ),
        CleanupCategory(
            id="dagster",
            title="🔧 Dagster storage (runs older than 7 days)",
            description=[
                "Dagster jobs store logs in .dagster_home; old run data can accumulate quickly.",
            ],
            estimate=_estimate_dagster_storage,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up old Dagster run storage?",
        ),
        CleanupCategory(
            id="node_artifacts",
            title="📦 JS/TS build caches (pnpm, Vite, Tailwind, Storybook, Playwright)",
            description=[
                "Cleans build outputs and caches listed in .gitignore for the pnpm workspace.",
            ],
            estimate=_estimate_node_artifacts,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up JavaScript build caches and artifacts?",
        ),
        CleanupCategory(
            id="rust",
            title="🦀 Rust Cargo targets",
            description=[
                "Removes Cargo 'target' directories from anywhere in the repository.",
                "Feature flag debug builds can accumulate ~400MB each.",
            ],
            estimate=_estimate_rust_targets,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up Rust target directories?",
        ),
        CleanupCategory(
            id="node_modules",
            title="⚠️  node_modules (pnpm workspace)",
            description=[
                "Deletes pnpm-managed node_modules directories across the workspace.",
                "You'll need to run 'pnpm install' afterwards to restore dependencies.",
            ],
            estimate=_estimate_node_modules,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up node_modules directories?",
            default_confirm=False,
            dry_run_message=("Would delete node_modules directories (requires 'pnpm install' afterwards)."),
            post_cleanup_message="   ⚠️  Remember to run: pnpm install",
        ),
    ]

    # Filter categories based on --area flag
    if area:
        # Convert area names (with hyphens) to category IDs (with underscores)
        enabled_ids = {area_name.replace("-", "_") for area_name in area}
        categories = [cat for cat in all_categories if cat.id in enabled_ids]
    else:
        categories = all_categories

    results: list[CleanupResult] = []
    for category in categories:
        results.append(_run_category(category, REPO_ROOT, dry_run, yes, silent=False))

    total_freed = sum(result.freed for result in results)
    non_counted = [
        category.title
        for category, result in zip(categories, results)
        if not category.include_in_total and result.ran_cleanup
    ]

    click.echo("\n" + "━" * 60)
    click.echo("\n✨ Summary")
    if dry_run:
        click.echo("   [DRY-RUN] No files were actually deleted.")
    else:
        if total_freed > 0:
            click.echo(f"   Total space freed: {_format_size(total_freed)}")
        elif any(result.ran_cleanup for result in results):
            click.echo("   Cleanup completed but no measurable files were removed.")
        else:
            click.echo("   No cleanup actions were run.")

        if non_counted:
            titles = ", ".join(non_counted)
            click.echo("   Note: " f"{titles} cleanup is not included in the total freed space.")


def _run_category(
    category: CleanupCategory,
    repo_root: Path,
    dry_run: bool,
    auto_confirm: bool,
    silent: bool = False,
) -> CleanupResult:
    """Execute a cleanup category interactively and return the outcome."""

    if not silent:
        click.echo("\n" + "━" * 60)
        click.echo(f"\n{category.title}")

        for line in category.description:
            click.echo(f"   {line}")

    estimate = category.estimate(repo_root)

    if not silent:
        for detail in estimate.details:
            click.echo(detail)

    if not estimate.available:
        return CleanupResult()

    if estimate.total_size <= 0 and category.skip_if_empty and not estimate.items:
        if not silent and not estimate.details:
            click.echo("   ✓ Already clean (0 bytes)")
        return CleanupResult()

    if not silent and estimate.total_size > 0:
        click.echo(f"   Estimated size: {_format_size(estimate.total_size)}")

    prompt = (
        category.confirmation_prompt
        if category.confirmation_prompt.endswith("?")
        else f"{category.confirmation_prompt}?"
    )

    if auto_confirm or (not silent and click.confirm(f"\n   {prompt}", default=category.default_confirm)):
        if dry_run:
            if not silent:
                if category.dry_run_message:
                    click.echo(f"   [DRY-RUN] {category.dry_run_message}")
                if category.include_in_total and estimate.total_size > 0:
                    click.echo(f"   [DRY-RUN] Would clean {_format_size(estimate.total_size)}")
                elif not category.include_in_total:
                    click.echo("   [DRY-RUN] Would execute cleanup command.")
            return CleanupResult()

        stats = category.cleanup(estimate, repo_root)

        if not silent:
            if category.include_in_total:
                if stats.freed > 0:
                    click.echo(f"   ✓ Cleaned {_format_size(stats.freed)}")
                else:
                    click.echo("   ✓ Cleanup completed (no files removed)")

            if category.post_cleanup_message:
                click.echo(category.post_cleanup_message)

        return CleanupResult(
            freed=stats.freed if category.include_in_total else 0.0,
            ran_cleanup=True,
            deleted_anything=stats.deleted_anything,
        )

    if not silent:
        click.echo("   ⏭️  Skipped")
    return CleanupResult()


def _estimate_flox_logs(repo_root: Path) -> CleanupEstimate:
    """Collect Flox log files older than 7 days under .flox/log."""

    flox_log_dir = repo_root / ".flox" / "log"
    if not flox_log_dir.exists():
        return CleanupEstimate(
            total_size=0.0,
            details=["   Flox log directory not found."],
            items=[],
        )

    cutoff = time.time() - (7 * 24 * 60 * 60)
    items: list[CleanupItem] = []
    total = 0.0
    for log_file in flox_log_dir.glob("*.log"):
        if not log_file.is_file():
            continue
        try:
            stat = log_file.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        # Only include files older than 7 days
        if stat.st_mtime >= cutoff:
            continue
        items.append(CleanupItem(log_file, stat.st_size, is_dir=False))
        total += stat.st_size

    details: list[str] = []
    relative_dir = flox_log_dir.relative_to(repo_root)
    if items:
        details.append(f"   Located {len(items)} log file(s) older than 7 days in {relative_dir}.")
        details.extend(_describe_items(items, repo_root, "   Sample log files:"))
    else:
        details.append(f"   No Flox log files older than 7 days in {relative_dir}.")

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_python_caches(repo_root: Path) -> CleanupEstimate:
    """Identify Python cache directories such as __pycache__ and mypy caches."""

    items = list(_collect_python_cache_dirs(repo_root))
    total = sum(item.size for item in items)

    if items:
        details = [f"   Found {len(items)} Python cache director{'ies' if len(items) != 1 else 'y'}."]
        details.extend(_describe_items(items, repo_root, "   Sample cache locations:"))
    else:
        details = ["   No Python cache directories detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_dagster_storage(repo_root: Path) -> CleanupEstimate:
    """Collect Dagster storage files older than seven days."""

    storage_dir = repo_root / ".dagster_home" / "storage"
    if not storage_dir.exists():
        return CleanupEstimate(
            total_size=0.0,
            details=["   Dagster storage directory not found."],
            items=[],
        )

    items = list(_collect_old_dagster_files(storage_dir))
    total = sum(item.size for item in items)

    details = [
        "   Removes execution logs older than 7 days to keep Dagster lean.",
    ]
    if items:
        details.append(f"   Found {len(items)} file(s) older than 7 days in {storage_dir.relative_to(repo_root)}.")
        details.extend(_describe_items(items, repo_root, "   Sample files:"))
    else:
        details.append("   No Dagster files older than 7 days detected.")

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_node_artifacts(repo_root: Path) -> CleanupEstimate:
    """Collect Node.js/TypeScript build caches and artifacts listed in .gitignore."""

    items = _collect_paths_from_patterns(repo_root, NODE_ARTIFACT_PATTERNS)
    total = sum(item.size for item in items)

    if items:
        details = [
            "   Cleans pnpm/Vite/Tailwind/Storybook/Playwright caches and build outputs.",
            f"   Found {len(items)} path(s) matching known artifact locations.",
        ]
        details.extend(_describe_items(items, repo_root, "   Sample paths:"))
    else:
        details = ["   No JavaScript build caches detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_rust_targets(repo_root: Path) -> CleanupEstimate:
    """Identify Cargo target directories in the rust/ workspace."""

    items = _collect_rust_target_dirs(repo_root)
    total = sum(item.size for item in items)

    if items:
        details = [
            f"   Found {len(items)} Cargo target director{'ies' if len(items) != 1 else 'y'} to remove.",
        ]
        details.extend(_describe_items(items, repo_root, "   Sample directories:"))
    else:
        details = ["   No Cargo target directories detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_node_modules(repo_root: Path) -> CleanupEstimate:
    """Gather pnpm workspace node_modules directories."""

    items = _collect_node_modules(repo_root)
    total = sum(item.size for item in items)

    if items:
        details = [
            f"   Found {len(items)} node_modules director{'ies' if len(items) != 1 else 'y'} managed by pnpm.",
        ]
        details.extend(_describe_items(items, repo_root, "   Sample directories:"))
    else:
        details = ["   No node_modules directories detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_docker_usage(repo_root: Path) -> CleanupEstimate:
    """Summarise Docker disk usage via `docker system df`. Repo root unused (compat)."""

    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return CleanupEstimate(
            total_size=0.0,
            items=[],
            details=["   Docker not available or not running; skipping."],
            available=False,
        )

    df_result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True, check=False)

    details = ["   Current Docker disk usage:"]
    if df_result.returncode == 0 and df_result.stdout.strip():
        details.extend([f"     {line}" for line in df_result.stdout.strip().splitlines()])
    else:
        details.append("     (Unable to retrieve docker system df output)")

    details.append("   Command to run: docker system prune -a --volumes -f")

    return CleanupEstimate(total_size=0.0, items=[], details=details)


def _cleanup_items(estimate: CleanupEstimate, _: Path) -> CleanupStats:
    """Delete all items in the estimate and report freed bytes."""

    freed = _delete_items(estimate.items)
    return CleanupStats(freed=freed, deleted_anything=freed > 0)


def _cleanup_docker(_: CleanupEstimate, __: Path) -> CleanupStats:
    """Execute docker system prune command."""

    click.echo()
    result = subprocess.run(["docker", "system", "prune", "-a", "--volumes", "-f"], check=False)
    if result.returncode == 0:
        click.echo("   ✓ Docker cleanup completed")
        return CleanupStats(deleted_anything=True)

    click.echo("   ⚠️  Docker cleanup failed")
    return CleanupStats(deleted_anything=False)


def _collect_python_cache_dirs(repo_root: Path) -> Iterable[CleanupItem]:
    """Yield CleanupItem objects for Python cache directories."""

    seen: set[Path] = set()
    for pattern in PYTHON_CACHE_PATTERNS:
        for cache_dir in repo_root.glob(f"**/{pattern}"):
            if any(part in {".git", "node_modules"} for part in cache_dir.parts):
                continue
            try:
                resolved = cache_dir.resolve()
            except (FileNotFoundError, PermissionError, RuntimeError):
                continue
            if resolved in seen or not cache_dir.is_dir():
                continue
            size = _get_dir_size(cache_dir)
            if size <= 0:
                continue
            seen.add(resolved)
            yield CleanupItem(cache_dir, size, is_dir=True)


def _collect_old_dagster_files(storage_dir: Path) -> Iterable[CleanupItem]:
    """Yield Dagster files older than seven days."""

    cutoff = time.time() - (7 * 24 * 60 * 60)
    for item in storage_dir.rglob("*"):
        if not item.is_file():
            continue
        try:
            stat = item.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if stat.st_mtime < cutoff and stat.st_size > 0:
            yield CleanupItem(item, stat.st_size, is_dir=False)


def _collect_paths_from_patterns(repo_root: Path, patterns: Sequence[str]) -> list[CleanupItem]:
    """Collect files/directories that match glob patterns relative to repo root."""

    items: list[CleanupItem] = []
    seen: set[Path] = set()

    for pattern in patterns:
        for path in repo_root.glob(pattern):
            try:
                resolved = path.resolve()
            except (FileNotFoundError, PermissionError, RuntimeError):
                continue
            if resolved in seen:
                continue
            seen.add(resolved)

            if path.is_dir():
                size = _get_dir_size(path)
                if size <= 0:
                    continue
                items.append(CleanupItem(path, size, is_dir=True))
            else:
                try:
                    size = path.stat().st_size
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                if size <= 0:
                    continue
                items.append(CleanupItem(path, size, is_dir=False))

    return items


def _collect_rust_target_dirs(repo_root: Path) -> list[CleanupItem]:
    """Collect Cargo target directories anywhere in the repository."""

    items: list[CleanupItem] = []
    seen: set[Path] = set()

    for target_dir in repo_root.glob("**/target"):
        if any(part in {".git", "node_modules"} for part in target_dir.parts):
            continue

        # Verify it's a Cargo target by checking for CACHEDIR.TAG or debug/release subdirs
        if (
            not (target_dir / "CACHEDIR.TAG").exists()
            and not (target_dir / "debug").exists()
            and not (target_dir / "release").exists()
        ):
            continue

        try:
            resolved = target_dir.resolve()
        except (FileNotFoundError, PermissionError, RuntimeError):
            continue
        if resolved in seen or not target_dir.is_dir():
            continue
        size = _get_dir_size(target_dir)
        if size <= 0:
            continue
        seen.add(resolved)
        items.append(CleanupItem(target_dir, size, is_dir=True))

    return items


def _collect_node_modules(repo_root: Path) -> list[CleanupItem]:
    """Collect top-level pnpm node_modules directories (skipping nested duplicates)."""

    items: list[CleanupItem] = []
    seen: set[Path] = set()

    for package_json in repo_root.rglob("package.json"):
        if "node_modules" in package_json.parts or ".git" in package_json.parts:
            continue
        node_modules_dir = package_json.parent / "node_modules"
        if not node_modules_dir.exists():
            continue
        try:
            resolved = node_modules_dir.resolve()
        except (FileNotFoundError, PermissionError, RuntimeError):
            continue
        if resolved in seen or not node_modules_dir.is_dir():
            continue
        size = _get_dir_size(node_modules_dir)
        if size <= 0:
            continue
        seen.add(resolved)
        items.append(CleanupItem(node_modules_dir, size, is_dir=True))

    return items


def _iter_named_directories(base: Path, name: str) -> Iterable[Path]:
    """Yield directories named `name`, skipping nested duplicates."""

    for path in base.glob(f"**/{name}"):
        if not path.is_dir():
            continue
        try:
            relative = path.relative_to(base)
        except ValueError:
            relative = path
        if name in relative.parts[:-1]:
            continue
        yield path


def _describe_items(items: Sequence[CleanupItem], repo_root: Path, heading: str) -> list[str]:
    """Return formatted lines describing a subset of cleanup items."""

    if not items:
        return []

    lines = [heading]
    for item in sorted(items, key=lambda entry: entry.path)[:MAX_SAMPLE_PATHS]:
        try:
            relative = item.path.relative_to(repo_root)
        except ValueError:
            relative = item.path
        lines.append(f"     - {relative} ({_format_size(item.size)})")

    if len(items) > MAX_SAMPLE_PATHS:
        lines.append(f"     … {len(items) - MAX_SAMPLE_PATHS} more")

    return lines


def _delete_items(items: Iterable[CleanupItem]) -> float:
    """Remove files and directories, returning the total freed bytes."""

    freed = 0.0
    for item in items:
        try:
            if item.is_dir:
                shutil.rmtree(item.path)
            else:
                item.path.unlink()
            freed += item.size
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return freed


def _get_dir_size(path: Path) -> float:
    """Compute directory size without following symlinked directories."""

    if not path.exists():
        return 0.0

    total = 0.0
    stack = [path]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except (FileNotFoundError, PermissionError, OSError):
                        continue
        except (FileNotFoundError, PermissionError, NotADirectoryError, OSError):
            continue

    return total


def _format_size(bytes_size: float) -> str:
    """Format bytes as a human-readable size string."""

    if bytes_size <= 0:
        return "0.0 B"

    for unit in ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} EiB"
