from unittest.mock import patch

from infi.clickhouse_orm.utils import import_submodules

from ee.clickhouse.sql.person import PERSONS_DISTINCT_ID_TABLE_MV_SQL
from posthog.constants import AnalyticsDBMS
from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.special_migrations.definition import SpecialMigrationDefinition, SpecialMigrationOperation
from posthog.special_migrations.setup import SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH
from posthog.test.base import BaseTest
from posthog.version_requirement import ServiceVersionRequirement


class TestSpecialMigrationDefinition(BaseTest):
    def test_get_special_migrations_without_staff_status(self):
        modules = import_submodules(SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH)
        example_migration = modules["example"].Migration()

        self.assertEqual(isinstance(example_migration, SpecialMigrationDefinition), True)
        self.assertEqual(isinstance(example_migration.operations[0], SpecialMigrationOperation), True)
        self.assertEqual(example_migration.description, "An example special migration.")
        self.assertEqual(example_migration.posthog_min_version, "1.29.0")
        self.assertEqual(example_migration.posthog_max_version, "1.30.0")
        self.assertEqual(example_migration.operations[-1].sql, PERSONS_DISTINCT_ID_TABLE_MV_SQL)
        self.assertEqual(example_migration.operations[-1].database, AnalyticsDBMS.CLICKHOUSE)
        self.assertEqual(isinstance(example_migration.service_version_requirements[0], ServiceVersionRequirement), True)
