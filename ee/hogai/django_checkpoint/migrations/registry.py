import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class MigrationRegistry:
    """
    Registry for managing checkpoint migrations in version order.

    The registry maintains an ordered list of migrations and provides
    methods to apply them to checkpoint data as needed.
    """

    def __init__(self):
        self._migrations: dict[int, type] = {}
        self._current_version = 1  # Latest version after all migrations

    def register_migration(self, migration_class: type) -> None:
        """
        Register a migration class with the registry.

        Version is inferred from the migration class module name.
        Expected format: _NNNN_description.py -> version NNNN

        Args:
            migration_class: Migration class with required methods
        """
        version = self.get_version_for_class(migration_class)
        if version in self._migrations:
            logger.warning(
                f"Migration version {version} already registered, overwriting "
                f"(existing: {self._migrations[version].__name__}, new: {migration_class.__name__})"
            )

        self._migrations[version] = migration_class

        # Update current version to highest registered migration
        self._current_version = max(self._migrations.keys()) if self._migrations else 1

    @property
    def current_version(self) -> int:
        """Get the current target schema version (highest migration)."""
        return self._current_version

    def get_migrations_needed(self, from_version: int) -> list[type]:
        """
        Get list of migrations needed to upgrade from a version.

        Args:
            from_version: Current schema version of the data

        Returns:
            List of migration classes to apply in order
        """
        needed_migrations = []

        for version in sorted(self._migrations.keys()):
            if version > from_version:
                needed_migrations.append(self._migrations[version])

        return needed_migrations

    def get_checkpoint_version(self, metadata: dict[str, Any]) -> int:
        """
        Get the current schema version of a checkpoint.

        Args:
            metadata: Checkpoint metadata dict

        Returns:
            Current schema version (0 for legacy checkpoints)
        """
        version_metadata = metadata.get("version_metadata", {})
        return version_metadata.get("schema_version", 0)

    def get_version_for_class(self, migration_class: type) -> int:
        """
        Extract version number from migration class module name.

        Expected format: _NNNN_description.py -> version NNNN
        E.g., _0001_add_version_metadata.py -> version 1

        Args:
            migration_class: Migration class

        Returns:
            Version number extracted from module name

        Raises:
            ValueError: If version cannot be extracted from module name
        """
        module_name = migration_class.__module__

        # Extract the filename from the module path
        # e.g., ee.hogai.django_checkpoint.migrations._0001_add_version_metadata -> _0001_add_version_metadata
        filename = module_name.split(".")[-1]

        # Match pattern _NNNN_description
        match = re.match(r"^_([0-9]+)_", filename)
        if not match:
            raise ValueError(
                f"Cannot extract version from migration module name '{module_name}'. "
                f"Expected format: _NNNN_description.py (e.g., _0001_add_version_metadata.py)"
            )

        version = int(match.group(1))
        return version


# Global registry instance
registry = MigrationRegistry()
