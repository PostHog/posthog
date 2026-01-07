from datetime import datetime

import pytest

from django.db import connection

from posthog.async_migrations.examples.test_migration import Migration
from posthog.async_migrations.runner import (
    attempt_migration_rollback,
    run_async_migration_next_op,
    start_async_migration,
)
from posthog.async_migrations.test.util import AsyncMigrationBaseTest, create_async_migration
from posthog.async_migrations.utils import update_async_migration
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from posthog.models.utils import UUIDT

pytestmark = pytest.mark.async_migrations


class TestRunner(AsyncMigrationBaseTest):
    def setUp(self):
        self.migration = Migration("TEST_MIGRATION")
        self.TEST_MIGRATION_DESCRIPTION = self.migration.description
        create_async_migration(name="test_migration", description=self.TEST_MIGRATION_DESCRIPTION)
        return super().setUp()

    # Run the full migration through
    def test_run_migration_in_full(self):
        self.migration.sec.reset_count()
        migration_successful = start_async_migration("test_migration")
        sm = AsyncMigration.objects.get(name="test_migration")

        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM test_async_migration")
            res = cursor.fetchone()

        assert res == ("a", "c")

        assert migration_successful
        assert sm.name == "test_migration"
        assert sm.description == self.TEST_MIGRATION_DESCRIPTION
        assert sm.status == MigrationStatus.CompletedSuccessfully
        assert sm.progress == 100
        errors = AsyncMigrationError.objects.filter(async_migration=sm)
        assert errors.count() == 0
        assert UUIDT.is_valid_uuid(sm.current_query_id)
        assert sm.current_operation_index == 7
        assert sm.posthog_min_version == "1.0.0"
        assert sm.posthog_max_version == "100000.0.0"
        assert sm.finished_at.day == datetime.today().day
        assert self.migration.sec.side_effect_count == 3
        assert self.migration.sec.side_effect_rollback_count == 0

    def test_rollback_migration(self):
        self.migration.sec.reset_count()

        migration_successful = start_async_migration("test_migration")

        assert migration_successful == True

        sm = AsyncMigration.objects.get(name="test_migration")

        attempt_migration_rollback(sm)
        sm.refresh_from_db()

        exception = None
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM test_async_migration")
        except Exception as e:
            exception = e

        assert 'relation "test_async_migration" does not exist' in str(exception)

        assert sm.status == MigrationStatus.RolledBack
        assert sm.progress == 0
        assert self.migration.sec.side_effect_count == 3
        assert self.migration.sec.side_effect_rollback_count == 3

    def test_rollback_migration_failure(self):
        migration_name = "test_with_rollback_exception"
        create_async_migration(name=migration_name)
        self.migration.sec.reset_count()
        migration_successful = start_async_migration(migration_name)
        assert migration_successful == True

        sm = AsyncMigration.objects.get(name=migration_name)

        attempt_migration_rollback(sm)
        sm.refresh_from_db()

        assert sm.status == MigrationStatus.Errored
        assert sm.current_operation_index == 1

    def test_run_async_migration_next_op(self):
        sm = AsyncMigration.objects.get(name="test_migration")

        update_async_migration(sm, status=MigrationStatus.Running)

        run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()
        assert sm.current_operation_index == 1
        assert sm.progress == int(100 * 1 / 7)

        run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()
        assert sm.current_operation_index == 2
        assert sm.progress == int(100 * 2 / 7)

        run_async_migration_next_op("test_migration", sm)

        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM test_async_migration")
            res = cursor.fetchone()

        assert res == ("a", "b")

        for _ in range(5):
            run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()
        assert sm.current_operation_index == 7
        assert sm.progress == 100
        assert sm.status == MigrationStatus.CompletedSuccessfully

        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM test_async_migration")
            res = cursor.fetchone()

        assert res == ("a", "c")

    def test_rollback_an_incomplete_migration(self):
        sm = AsyncMigration.objects.get(name="test_migration")
        sm.status = MigrationStatus.Running
        sm.save()

        run_async_migration_next_op("test_migration", sm)
        run_async_migration_next_op("test_migration", sm)
        run_async_migration_next_op("test_migration", sm)
        run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()
        assert sm.current_operation_index == 4
        assert self.migration.sec.side_effect_count == 1

        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM test_async_migration")
            res = cursor.fetchone()

        assert res == ("a", "b")

        attempt_migration_rollback(sm)
        sm.refresh_from_db()

        exception = None
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM test_async_migration")
        except Exception as e:
            exception = e

        assert 'relation "test_async_migration" does not exist' in str(exception)
        assert sm.status == MigrationStatus.RolledBack
        assert sm.progress == 0
        assert self.migration.sec.side_effect_rollback_count == 2  # checking we ran current index rollback too

    def test_fail_at_startup_with_no_definition(self):
        sm = AsyncMigration.objects.get(name="test_migration")
        sm.name = "no_such_definition"
        sm.save()

        migration_successful = start_async_migration("no_such_definition")
        assert not migration_successful
        sm.refresh_from_db()
        assert sm.status == MigrationStatus.FailedAtStartup
