import os
import re

from django.db.migrations.executor import MigrationExecutor

from posthog.person_db_router import PERSONS_DB_MODELS


class RoutingMigrationExecutor(MigrationExecutor):
    """Custom migration executor that can route migrations based on the migration name or number"""

    MIGRATION_CUTOFFS = {
        "posthog": {
            "cutoff": os.getenv("PERSONS_DB_MIGRATION_CUTOFF", ""),
            "default_db": "default",
            "persons_db": "persons_db_writer",
        }
    }

    def __init__(self, connection, progress_callback=None):
        super().__init__(connection, progress_callback)
        self._current_migration = None

    def migrate(self, targets, plan=None, state=None, fake=False, fake_initial=False):
        """Override the main migrate method"""
        return super().migrate(targets, plan, state, fake, fake_initial)

    def apply_migration(self, state, migration, fake=False, fake_initial=False):
        """Override to capture current migration being applied"""
        self._current_migration = migration

        if self._should_skip_migration(migration):
            # Mark it as applied without running
            self.recorder.record_applied(migration.app_label, migration.name)
            return state

        return super().apply_migration(state, migration, fake, fake_initial)

    def _should_skip_migration(self, migration):
        """Determine if migration should be skipped on current database"""
        app_config = self.MIGRATION_CUTOFFS.get(migration.app_label)
        if not app_config:
            return False

        cutoff = app_config.get("cutoff", "")
        if not cutoff:
            return False

        # Extract migration number
        match = re.match(r"^(\d+)", migration.name)
        if not match:
            return False

        migration_number = match.group(1)
        current_db = self.connection.alias

        # For migrations after cutoff, check model-specific routing
        if migration_number >= int(cutoff):
            affected_models = self._get_migration_models(migration)

            if self._affects_person_models(affected_models) and current_db == app_config["default_db"]:
                return True

            if self._affects_non_person_models(affected_models) and current_db == app_config["persons_db"]:
                return True

        return False

    def _get_migration_models(self, migration):
        """Extract model names affected by this migration"""
        models = set()

        for operation in migration.operations:
            # Handle different types of operations
            if hasattr(operation, "model_name"):
                models.add(operation.model_name.lower())
            elif hasattr(operation, "name"):
                # For CreateModel, DeleteModel, etc.
                models.add(operation.name.lower())
            elif hasattr(operation, "model_name_lower"):
                models.add(operation.model_name_lower)

        return models

    def _affects_person_models(self, models):
        """Check if any of the models are person models"""
        return bool(models & PERSONS_DB_MODELS)

    def _affects_non_person_models(self, models):
        """Check if any of the models are non-person models"""
        non_person_models = models - PERSONS_DB_MODELS
        return bool(non_person_models)
