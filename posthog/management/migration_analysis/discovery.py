"""
Shared utilities for migration management commands.

Provides common functionality for discovering, validating, and loading
Django migrations from file paths.
"""

# ruff: noqa: T201 allow print statements

import os
import re
import sys
import select
from dataclasses import dataclass

from django.db.migrations.loader import MigrationLoader


@dataclass
class MigrationInfo:
    """Represents a parsed migration file"""

    path: str
    app_label: str
    migration_name: str


class MigrationDiscovery:
    """Handles discovery and loading of Django migrations"""

    @staticmethod
    def read_paths_from_stdin(timeout: int = 1) -> list[str]:
        """
        Read migration file paths from stdin with a timeout.

        Args:
            timeout: Timeout in seconds to wait for stdin

        Returns:
            List of migration file paths
        """
        if select.select([sys.stdin], [], [], timeout)[0]:
            return [line.strip() for line in sys.stdin.readlines() if line.strip()]
        return []

    @staticmethod
    def parse_migration_path(path: str) -> MigrationInfo:
        """
        Parse a migration file path to extract app label and migration name.

        Supports both:
        - New products structure: products/product_name/backend/migrations/NNNN_name.py
        - Legacy structure: app_name/migrations/NNNN_name.py

        Args:
            path: File path to migration

        Returns:
            MigrationInfo with parsed components

        Raises:
            ValueError: If path format is not recognized
        """
        # Try products structure first
        products_match = re.findall(r"products/([a-z_]+)/backend/migrations/([a-zA-Z_0-9]+)\.py", path)
        if products_match:
            app_label, migration_name = products_match[0]
            return MigrationInfo(path=path, app_label=app_label, migration_name=migration_name)

        # Fall back to generic structure (posthog, ee, etc)
        generic_match = re.findall(r"([a-z]+)\/migrations\/([a-zA-Z_0-9]+)\.py", path)
        if generic_match:
            app_label, migration_name = generic_match[0]
            return MigrationInfo(path=path, app_label=app_label, migration_name=migration_name)

        raise ValueError(f"Could not parse migration path: {path}")

    @staticmethod
    def validate_path(path: str) -> tuple[bool, str | None]:
        """
        Validate a migration file path for security and correctness.

        Args:
            path: File path to validate

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is None
        """
        if not path:
            return False, "Empty path"

        if not path.endswith(".py"):
            return False, f"Not a Python file: {path}"

        if ".." in path or path.startswith("/"):
            return False, f"Suspicious path (possible path traversal): {path}"

        return True, None

    @staticmethod
    def load_migration(migration_info: MigrationInfo):
        """
        Load a Django migration object from a MigrationInfo.

        Args:
            migration_info: Parsed migration information

        Returns:
            Django migration object from the disk_migrations registry

        Raises:
            KeyError: If migration is not found in the loader
        """
        loader = MigrationLoader(None)
        migration_key = (migration_info.app_label, migration_info.migration_name)

        if migration_key not in loader.disk_migrations:
            raise KeyError(
                f"Migration not found: {migration_info.app_label}.{migration_info.migration_name} "
                f"(from {migration_info.path})"
            )

        return loader.disk_migrations[migration_key]

    @classmethod
    def process_migration_paths(
        cls,
        paths: list[str],
        *,
        skip_invalid: bool = False,
        fail_on_ci: bool = True,
    ) -> list[tuple[MigrationInfo, object]]:
        """
        Process a list of migration paths into loaded migration objects.

        Args:
            paths: List of migration file paths
            skip_invalid: If True, skip invalid paths; if False, exit on error
            fail_on_ci: If True and in CI, exit on any error

        Returns:
            List of (MigrationInfo, migration_object) tuples
        """
        results = []
        loader = MigrationLoader(None)  # Reuse loader for efficiency

        for path in paths:
            # Validate path
            is_valid, error = cls.validate_path(path)
            if not is_valid:
                print(f"⚠️  Skipping: {error}")
                if not skip_invalid and os.getenv("CI") and fail_on_ci:
                    sys.exit(1)
                continue

            try:
                # Parse path
                migration_info = cls.parse_migration_path(path)

                # Load migration
                migration_key = (migration_info.app_label, migration_info.migration_name)
                if migration_key not in loader.disk_migrations:
                    print(
                        f"⚠️  Warning: Could not find migration {migration_info.app_label}.{migration_info.migration_name}"
                    )
                    if os.getenv("CI") and fail_on_ci:
                        sys.exit(1)
                    continue

                migration = loader.disk_migrations[migration_key]
                results.append((migration_info, migration))

            except (ValueError, KeyError) as e:
                print(f"⚠️  Error processing {path}: {e}")
                if os.getenv("CI") and fail_on_ci:
                    sys.exit(1)
                if not skip_invalid:
                    raise

        return results
