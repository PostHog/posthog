from datetime import datetime
from unittest.mock import patch

from infi.clickhouse_orm.utils import import_submodules

from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.team import Team
from posthog.models.utils import UUIDT
from posthog.special_migrations.examples.test import Migration
from posthog.special_migrations.runner import attempt_migration_rollback, start_special_migration
from posthog.special_migrations.test.util import create_special_migration
from posthog.test.base import BaseTest

TEST_MIGRATION_DESCRIPTION = Migration().description


class TestRunner(BaseTest):
    def setUp(self):
        create_special_migration(name="test", description=TEST_MIGRATION_DESCRIPTION)
        return super().setUp()

    # Run the full migration through
    def test_run_migration_in_full(self):
        migration_successful = start_special_migration("test")
        sm = SpecialMigration.objects.get(name="test")

        self.assertEqual(migration_successful, True)
        self.assertEqual(sm.name, "test")
        self.assertEqual(sm.description, TEST_MIGRATION_DESCRIPTION)
        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.progress, 100)
        self.assertEqual(sm.last_error, "")
        self.assertEqual(UUIDT.is_valid_uuid(sm.current_query_id), True)
        self.assertEqual(sm.current_operation_index, 4)
        self.assertEqual(sm.posthog_min_version, "1.0.0")
        self.assertEqual(sm.posthog_max_version, "100000.0.0")
        self.assertEqual(sm.finished_at.day, datetime.today().day)

    def test_rollback_migration(self):

        migration_successful = start_special_migration("test")

        self.assertEqual(migration_successful, True)

        sm = SpecialMigration.objects.get(name="test")

        attempt_migration_rollback(sm)

        sm.refresh_from_db()
        self.assertEqual(sm.status, MigrationStatus.RolledBack)
        self.assertEqual(sm.progress, 0)
