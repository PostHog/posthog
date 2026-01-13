"""Shared utilities for Django migration management.

This module contains common constants, patterns, and functions used by both:
- hogli/migrations.py (CLI tool)
- posthog/management/commands/migrate.py (Django command extension)

Centralizing this code ensures consistent validation and caching behavior.
"""

from __future__ import annotations

import re
import shutil
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Cache directory for migration files
# Used for storing migration files so they can be rolled back after branch switching
MIGRATION_CACHE_DIR = Path.home() / ".cache" / "posthog-migrations"

# Pattern to validate migration names (without .py extension)
# Must start with 4 digits, underscore, then alphanumeric/underscores only
# Examples: "0001_initial", "0952_add_sync_test_branch_two"
MIGRATION_NAME_PATTERN = re.compile(r"^(\d{4})_[a-zA-Z0-9_]+$")

# Pattern to validate app names (valid Python package names)
# Must start with letter, then letters/numbers/underscores
# Examples: "posthog", "ee", "web_analytics"
APP_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


def validate_migration_path_components(app: str, name: str) -> None:
    """Validate app and migration name to prevent path traversal attacks.

    This is a security-critical function. Both app and migration names are used
    to construct file paths for caching. Invalid characters could allow writing
    files outside the cache directory.

    Args:
        app: The Django app label (e.g., "posthog", "ee")
        name: The migration name without .py extension (e.g., "0001_initial")

    Raises:
        ValueError: If either component contains invalid characters
    """
    if not APP_NAME_PATTERN.match(app):
        raise ValueError(f"Invalid app name: {app}")
    if not MIGRATION_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid migration name: {name}")


def is_valid_migration_path(app: str, name: str) -> bool:
    """Check if app and migration name are valid (non-raising version).

    Args:
        app: The Django app label
        name: The migration name without .py extension

    Returns:
        True if both components are valid, False otherwise
    """
    try:
        validate_migration_path_components(app, name)
        return True
    except ValueError:
        return False


def get_cache_path(app: str, name: str) -> Path:
    """Get the cache path for a migration file.

    Validates inputs before constructing path to prevent path traversal.

    Args:
        app: The Django app label
        name: The migration name without .py extension

    Returns:
        Path to the cached migration file

    Raises:
        ValueError: If app or name contains invalid characters
    """
    validate_migration_path_components(app, name)
    return MIGRATION_CACHE_DIR / app / f"{name}.py"


def get_cached_migration(app: str, name: str) -> Path | None:
    """Get a cached migration file if it exists.

    Args:
        app: The Django app label
        name: The migration name without .py extension

    Returns:
        Path to cached file if it exists, None otherwise.
        Returns None if validation fails (invalid app/name).
    """
    try:
        cache_path = get_cache_path(app, name)
        return cache_path if cache_path.exists() else None
    except ValueError:
        return None


def cache_migration_file(app: str, name: str, source_path: Path) -> bool:
    """Cache a migration file for later rollback.

    Creates the cache directory structure if needed and copies the migration
    file to the cache location.

    Args:
        app: The Django app label
        name: The migration name without .py extension
        source_path: Path to the source migration file

    Returns:
        True if caching succeeded, False if app name is invalid

    Raises:
        OSError: If creating the cache directory or copying the file fails
    """
    try:
        cache_path = get_cache_path(app, name)
    except ValueError:
        return False

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, cache_path)
        return True
    except OSError as e:
        raise OSError(f"Failed to cache {app}.{name}: {e}") from e


# Core PostHog apps that have migrations we manage
# These are always included; product apps are discovered dynamically
CORE_MANAGED_APPS = frozenset({"posthog", "ee", "rbac"})


def discover_product_apps(base_dir: Path) -> set[str]:
    """Discover product apps with migrations in products/*/backend/migrations/.

    Args:
        base_dir: The repository root directory

    Returns:
        Set of product app names that have migration directories
    """
    apps: set[str] = set()
    products_dir = base_dir / "products"
    if products_dir.exists():
        for product_dir in products_dir.iterdir():
            if product_dir.is_dir():
                migrations_dir = product_dir / "backend" / "migrations"
                if migrations_dir.exists():
                    apps.add(product_dir.name)
    return apps


def get_managed_app_names(base_dir: Path) -> set[str]:
    """Get all managed app names (core + product apps).

    Args:
        base_dir: The repository root directory

    Returns:
        Set of app names we manage migrations for
    """
    return set(CORE_MANAGED_APPS) | discover_product_apps(base_dir)


def get_managed_app_paths(base_dir: Path) -> dict[str, Path]:
    """Get all managed apps with their migration directory paths.

    Args:
        base_dir: The repository root directory

    Returns:
        Dict mapping app names to their migration directories
    """
    apps = {
        "posthog": base_dir / "posthog" / "migrations",
        "ee": base_dir / "ee" / "migrations",
        "rbac": base_dir / "posthog" / "rbac" / "migrations",
    }

    # Add product apps using the shared discovery function
    for product_name in discover_product_apps(base_dir):
        apps[product_name] = base_dir / "products" / product_name / "backend" / "migrations"

    return apps


# Context managers for rollback operations


@contextmanager
def temporary_migration_file(cache_path: Path, target_path: Path) -> Iterator[None]:
    """Context manager that copies a cached migration to target and cleans up after."""
    shutil.copy2(cache_path, target_path)
    try:
        yield
    finally:
        target_path.unlink(missing_ok=True)


@contextmanager
def temporary_max_migration(migrations_dir: Path, migration_name: str) -> Iterator[None]:
    """Context manager that temporarily updates max_migration.txt and restores it after.

    Only modifies the file if it already exists - creating it when absent could
    confuse Django into thinking the app uses squashed migrations.
    """
    max_migration_path = migrations_dir / "max_migration.txt"
    original_value = None

    if max_migration_path.exists():
        original_value = max_migration_path.read_text().strip()
        max_migration_path.write_text(f"{migration_name}\n")

    try:
        yield
    finally:
        if original_value is not None:
            max_migration_path.write_text(f"{original_value}\n")


@contextmanager
def hidden_conflicting_migrations(migrations_dir: Path, migration_name: str) -> Iterator[None]:
    """Context manager that hides conflicting migrations and restores them after.

    Conflicting migrations are those with the same number prefix but different names.
    For example, 0952_add_feature conflicts with 0952_other_feature.
    """
    migration_prefix = migration_name.split("_")[0]
    hidden: list[tuple[Path, Path]] = []

    try:
        # Hide conflicting migrations inside try block so partial failures
        # still trigger cleanup of already-hidden files
        for migration_file in migrations_dir.glob(f"{migration_prefix}_*.py"):
            if migration_file.name != f"{migration_name}.py":
                hidden_path = migration_file.with_suffix(".py.hidden")
                migration_file.rename(hidden_path)
                hidden.append((migration_file, hidden_path))

        yield
    finally:
        for original, hidden_path in hidden:
            if hidden_path.exists():
                if original.exists():
                    # Another process created a file at the original path - don't overwrite
                    warnings.warn(
                        f"Cannot restore {hidden_path} - {original} already exists",
                        stacklevel=2,
                    )
                else:
                    hidden_path.rename(original)
