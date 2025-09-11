import pytest
from posthog.test.base import BaseTest

from infi.clickhouse_orm.utils import import_submodules

from posthog.async_migrations.definition import AsyncMigrationDefinition, AsyncMigrationOperation
from posthog.async_migrations.setup import (
    ASYNC_MIGRATIONS_EXAMPLE_MODULE_PATH,
    get_async_migration_definition,
    setup_async_migrations,
)
from posthog.models.async_migration import AsyncMigration
from posthog.version_requirement import ServiceVersionRequirement

pytestmark = pytest.mark.async_migrations


class TestAsyncMigrationDefinition(BaseTest):
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
        self.assertTrue(
            isinstance(
                example_migration.service_version_requirements[0],
                ServiceVersionRequirement,
            )
        )

    def test_get_migration_instance_and_parameters(self):
        setup_async_migrations(ignore_posthog_version=True)

        MIGRATION_NAME = "0007_persons_and_groups_on_events_backfill"

        definition = get_async_migration_definition(MIGRATION_NAME)
        instance = AsyncMigration.objects.get(name=MIGRATION_NAME)

        self.assertEqual(definition.migration_instance(), instance)

        self.assertEqual(
            definition.get_parameter("PERSON_DICT_CACHE_SIZE"),
            definition.parameters["PERSON_DICT_CACHE_SIZE"][0],
        )

        instance.parameters = {"PERSON_DICT_CACHE_SIZE": 123}
        instance.save()
        self.assertEqual(definition.get_parameter("PERSON_DICT_CACHE_SIZE"), 123)
