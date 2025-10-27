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

import subprocess
from pathlib import Path

import click
from hogli.core.cli import cli

# Add your Click commands below this line


@cli.command(name="doctor:disk", help="Interactive disk space cleanup for common PostHog dev bloat")
@click.option("--dry-run", is_flag=True, help="Show what would be cleaned without deleting")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm all cleanup operations")
def doctor_disk(dry_run: bool, yes: bool) -> None:
    """Clean up disk space by removing caches and unused Docker resources.

    Interactively prompts for each cleanup category:
    - Flox logs (can grow to 32GB+)
    - Docker system (unused images, containers, build cache)
    - Python caches (__pycache__, .mypy_cache, .pytest_cache)
    - Dagster storage (runs/logs older than 7 days)
    - Node.js caches (.parcel-cache, .eslintcache, etc.)
    - node_modules (requires pnpm install after)

    Use --dry-run to preview what would be cleaned.
    Use --yes to auto-confirm all operations.
    """
    from hogli.core.manifest import REPO_ROOT

    click.echo("🔍 PostHog Disk Space Cleanup\n")

    if dry_run:
        click.echo("🚀 Running in DRY-RUN mode - no files will be deleted\n")

    total_freed = 0.0

    # Category 1: Flox logs
    click.echo("━" * 60)
    click.echo("\n📁 Flox logs (.flox/log/)")

    flox_log_dir = REPO_ROOT / ".flox" / "log"
    flox_size = _get_dir_size(flox_log_dir) if flox_log_dir.exists() else 0

    if flox_size > 0:
        click.echo(f"   Estimated size: {_format_size(flox_size)}")
        click.echo("   ⚠️  Can grow to 32GB+ if not cleaned regularly")
        click.echo("   Action: Delete all .log files")

        if yes or click.confirm("\n   Clean up Flox logs?", default=True):
            if not dry_run:
                freed = _clean_flox_logs(flox_log_dir)
                total_freed += freed
                click.echo(f"   ✓ Cleaned {_format_size(freed)}")
            else:
                click.echo(f"   [DRY-RUN] Would clean {_format_size(flox_size)}")
        else:
            click.echo("   ⏭️  Skipped")
    else:
        click.echo("   ✓ Already clean (0 bytes)")

    # Category 2: Docker system
    click.echo("\n" + "━" * 60)
    click.echo("\n🐳 Docker system (unused images, containers, build cache)")

    try:
        # Check if Docker is available and get current state
        subprocess.run(["docker", "info"], capture_output=True, check=True)

        # Show what's reclaimable using docker system df
        df_result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True, check=False)
        if df_result.returncode == 0:
            click.echo("   Current Docker disk usage:")
            for line in df_result.stdout.strip().split("\n"):
                click.echo(f"     {line}")

        click.echo("\n   Action: Run 'docker system prune -a --volumes -f'")

        if yes or click.confirm("\n   Clean up Docker system?", default=True):
            if not dry_run:
                # Let Docker handle the cleanup and show output
                click.echo()
                result = subprocess.run(["docker", "system", "prune", "-a", "--volumes", "-f"], check=False)
                if result.returncode == 0:
                    click.echo("\n   ✓ Docker cleanup completed")
                else:
                    click.echo("\n   ⚠️  Docker cleanup failed")
            else:
                click.echo("   [DRY-RUN] Would run: docker system prune -a --volumes -f")
                click.echo("   [DRY-RUN] This would reclaim the space shown in RECLAIMABLE column above")
        else:
            click.echo("   ⏭️  Skipped")
    except (FileNotFoundError, subprocess.CalledProcessError):
        click.echo("   ⏭️  Docker not available or not running")

    # Category 3: Python caches
    click.echo("\n" + "━" * 60)
    click.echo("\n🐍 Python caches (__pycache__, .mypy_cache, .pytest_cache)")

    python_cache_size = _get_python_cache_size(REPO_ROOT)

    if python_cache_size > 0:
        click.echo(f"   Estimated size: {_format_size(python_cache_size)}")
        click.echo("   Action: Delete all Python cache directories")

        if yes or click.confirm("\n   Clean up Python caches?", default=True):
            if not dry_run:
                freed = _clean_python_caches(REPO_ROOT)
                total_freed += freed
                click.echo(f"   ✓ Cleaned {_format_size(freed)}")
            else:
                click.echo(f"   [DRY-RUN] Would clean {_format_size(python_cache_size)}")
        else:
            click.echo("   ⏭️  Skipped")
    else:
        click.echo("   ✓ Already clean (0 bytes)")

    # Category 4: Dagster storage
    click.echo("\n" + "━" * 60)
    click.echo("\n🔧 Dagster storage (runs older than 7 days)")

    dagster_dir = REPO_ROOT / ".dagster_home"
    dagster_size = _get_old_dagster_size(dagster_dir) if dagster_dir.exists() else 0

    if dagster_size > 0:
        click.echo(f"   Estimated size: {_format_size(dagster_size)}")
        click.echo("   Action: Keep recent runs, delete old execution logs")

        if yes or click.confirm("\n   Clean up old Dagster storage?", default=True):
            if not dry_run:
                freed = _clean_old_dagster(dagster_dir)
                total_freed += freed
                click.echo(f"   ✓ Cleaned {_format_size(freed)}")
            else:
                click.echo(f"   [DRY-RUN] Would clean {_format_size(dagster_size)}")
        else:
            click.echo("   ⏭️  Skipped")
    else:
        click.echo("   ✓ Already clean (0 bytes)")

    # Category 5: Node.js caches
    click.echo("\n" + "━" * 60)
    click.echo("\n📦 Node.js caches (.parcel-cache, .eslintcache, etc.)")

    node_cache_size = _get_node_cache_size(REPO_ROOT)

    if node_cache_size > 0:
        click.echo(f"   Estimated size: {_format_size(node_cache_size)}")
        click.echo("   Action: Delete cache directories")

        if yes or click.confirm("\n   Clean up Node caches?", default=True):
            if not dry_run:
                freed = _clean_node_caches(REPO_ROOT)
                total_freed += freed
                click.echo(f"   ✓ Cleaned {_format_size(freed)}")
            else:
                click.echo(f"   [DRY-RUN] Would clean {_format_size(node_cache_size)}")
        else:
            click.echo("   ⏭️  Skipped")
    else:
        click.echo("   ✓ Already clean (0 bytes)")

    # Category 6: node_modules (warning)
    click.echo("\n" + "━" * 60)
    click.echo("\n⚠️  node_modules/ (requires reinstall)")

    node_modules_size = _get_node_modules_size(REPO_ROOT)

    if node_modules_size > 0:
        click.echo(f"   Estimated size: {_format_size(node_modules_size)}")
        click.echo("   Action: Delete all node_modules + require 'pnpm install'")
        click.echo("   ⚠️  You will need to run 'pnpm install' after this")

        if yes or click.confirm("\n   Clean up node_modules?", default=False):
            if not dry_run:
                freed = _clean_node_modules(REPO_ROOT)
                total_freed += freed
                click.echo(f"   ✓ Cleaned {_format_size(freed)}")
                click.echo("   ⚠️  Remember to run: pnpm install")
            else:
                click.echo(f"   [DRY-RUN] Would clean {_format_size(node_modules_size)}")
        else:
            click.echo("   ⏭️  Skipped")
    else:
        click.echo("   ✓ No node_modules found")

    # Summary
    click.echo("\n" + "━" * 60)
    click.echo("\n✨ Summary")
    if dry_run:
        click.echo("   [DRY-RUN] No files were actually deleted")
    elif total_freed > 0:
        click.echo(f"   Total space freed: {_format_size(total_freed)}")
        click.echo("   (Docker cleanup not included in total)")
    else:
        click.echo("   No files were deleted")


def _get_dir_size(path: Path) -> float:
    """Get total size of directory in bytes."""
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except (PermissionError, FileNotFoundError):
        pass
    return total


def _format_size(bytes_size: float) -> str:
    """Format bytes as human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def _clean_flox_logs(flox_log_dir: Path) -> float:
    """Delete all Flox log files and return bytes freed."""
    freed = 0.0
    try:
        for log_file in flox_log_dir.glob("*.log"):
            freed += log_file.stat().st_size
            log_file.unlink()
    except (PermissionError, FileNotFoundError):
        pass
    return freed


def _get_python_cache_size(repo_root: Path) -> float:
    """Get total size of Python cache directories."""
    total = 0.0
    cache_patterns = ["__pycache__", ".mypy_cache", ".pytest_cache"]

    for pattern in cache_patterns:
        for cache_dir in repo_root.rglob(pattern):
            if cache_dir.is_dir():
                total += _get_dir_size(cache_dir)

    return total


def _clean_python_caches(repo_root: Path) -> float:
    """Delete Python cache directories and return bytes freed."""
    import shutil

    freed = 0.0
    cache_patterns = ["__pycache__", ".mypy_cache", ".pytest_cache"]

    for pattern in cache_patterns:
        for cache_dir in repo_root.rglob(pattern):
            if cache_dir.is_dir():
                try:
                    freed += _get_dir_size(cache_dir)
                    shutil.rmtree(cache_dir)
                except (PermissionError, FileNotFoundError):
                    pass

    return freed


def _get_old_dagster_size(dagster_dir: Path) -> float:
    """Get size of Dagster storage older than 7 days."""
    import time

    total = 0.0
    seven_days_ago = time.time() - (7 * 24 * 60 * 60)

    storage_dir = dagster_dir / "storage"
    if storage_dir.exists():
        for item in storage_dir.rglob("*"):
            if item.is_file():
                try:
                    if item.stat().st_mtime < seven_days_ago:
                        total += item.stat().st_size
                except (PermissionError, FileNotFoundError):
                    pass

    return total


def _clean_old_dagster(dagster_dir: Path) -> float:
    """Delete Dagster files older than 7 days and return bytes freed."""
    import time

    freed = 0.0
    seven_days_ago = time.time() - (7 * 24 * 60 * 60)

    storage_dir = dagster_dir / "storage"
    if storage_dir.exists():
        for item in storage_dir.rglob("*"):
            if item.is_file():
                try:
                    if item.stat().st_mtime < seven_days_ago:
                        freed += item.stat().st_size
                        item.unlink()
                except (PermissionError, FileNotFoundError):
                    pass

    return freed


def _get_node_cache_size(repo_root: Path) -> float:
    """Get total size of Node.js cache directories."""
    total = 0.0
    cache_items = [
        ".parcel-cache",
        ".eslintcache",
        "frontend/.cache",
    ]

    for item in cache_items:
        cache_path = repo_root / item
        if cache_path.exists():
            if cache_path.is_dir():
                total += _get_dir_size(cache_path)
            else:
                total += cache_path.stat().st_size

    return total


def _clean_node_caches(repo_root: Path) -> float:
    """Delete Node.js cache directories and return bytes freed."""
    import shutil

    freed = 0.0
    cache_items = [
        ".parcel-cache",
        ".eslintcache",
        "frontend/.cache",
    ]

    for item in cache_items:
        cache_path = repo_root / item
        if cache_path.exists():
            try:
                if cache_path.is_dir():
                    freed += _get_dir_size(cache_path)
                    shutil.rmtree(cache_path)
                else:
                    freed += cache_path.stat().st_size
                    cache_path.unlink()
            except (PermissionError, FileNotFoundError):
                pass

    return freed


def _get_node_modules_size(repo_root: Path) -> float:
    """Get total size of all node_modules directories."""
    total = 0.0

    for node_modules_dir in repo_root.rglob("node_modules"):
        if node_modules_dir.is_dir():
            total += _get_dir_size(node_modules_dir)

    return total


def _clean_node_modules(repo_root: Path) -> float:
    """Delete all node_modules directories and return bytes freed."""
    import shutil

    freed = 0.0

    for node_modules_dir in repo_root.rglob("node_modules"):
        if node_modules_dir.is_dir():
            try:
                freed += _get_dir_size(node_modules_dir)
                shutil.rmtree(node_modules_dir)
            except (PermissionError, FileNotFoundError):
                pass

    return freed
