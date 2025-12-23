"""Shared utilities for Django migration management.

This module contains common constants, patterns, and functions used by both:
- hogli/migrations.py (CLI tool)
- posthog/management/commands/migrate.py (Django command extension)

Centralizing this code ensures consistent validation and caching behavior.
"""

from __future__ import annotations

import re
import shutil
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
        True if caching succeeded, False otherwise
    """
    try:
        cache_path = get_cache_path(app, name)
    except ValueError:
        return False

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(source_path, cache_path)
        return True
    except Exception:
        return False


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

    # Add product apps
    products_dir = base_dir / "products"
    if products_dir.exists():
        for product_dir in products_dir.iterdir():
            if product_dir.is_dir():
                migrations_dir = product_dir / "backend" / "migrations"
                if migrations_dir.exists():
                    apps[product_dir.name] = migrations_dir

    return apps
