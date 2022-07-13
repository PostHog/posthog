import pytest
from infi.clickhouse_orm.utils import import_submodules

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.async_migrations.setup import ASYNC_MIGRATIONS_EXAMPLE_MODULE_PATH
from posthog.test.base import BaseTest
from posthog.version_requirement import ServiceVersionRequirement


class TestAsyncMigrationDefinition(BaseTest):
    @pytest.mark.ee
    def test_get_async_migration_definition(self):
        from posthog.async_migrations.examples.example import example_fn, example_rollback_fn

        modules = import_submodules(ASYNC_MIGRATIONS_EXAMPLE_MODULE_PATH)
        example_migration = modules["example"].Migration("example")

        self.assertTrue(isinstance(example_migration, AsyncMigrationDefinition))
        self.assertTrue(isinstance(example_migration.operations[0], AsyncMigrationOperation))
        self.assertEqual(example_migration.description, "An example async migration.")
        self.assertEqual(example_migration.posthog_min_version, "1.29.0")
        self.assertEqual(example_migration.posthog_max_version, "1.30.0")
        self.assertEqual(example_migration.operations[-1].fn, example_fn)
        self.assertEqual(example_migration.operations[-1].rollback_fn, example_rollback_fn)
        self.assertTrue(isinstance(example_migration.service_version_requirements[0], ServiceVersionRequirement))
