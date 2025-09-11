from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from posthog.async_migrations.definition import AsyncMigrationOperationSQL
from posthog.async_migrations.test.util import AsyncMigrationBaseTest, create_async_migration
from posthog.async_migrations.utils import (
    complete_migration,
    execute_on_each_shard,
    execute_op,
    force_stop_migration,
    process_error,
    trigger_migration,
)
from posthog.constants import AnalyticsDBMS
from posthog.models.async_migration import AsyncMigrationError, MigrationStatus

pytestmark = pytest.mark.async_migrations

DEFAULT_CH_OP = AsyncMigrationOperationSQL(sql="SELECT 1", rollback=None, timeout_seconds=10)

DEFAULT_POSTGRES_OP = AsyncMigrationOperationSQL(database=AnalyticsDBMS.POSTGRES, sql="SELECT 1", rollback=None)


class TestUtils(AsyncMigrationBaseTest):
    @patch("posthog.clickhouse.client.sync_execute")
    def test_execute_op_clickhouse(self, mock_sync_execute):
        execute_op(DEFAULT_CH_OP, "some_id")

        # correctly routes to ch
        mock_sync_execute.assert_called_once_with("SELECT 1", None, settings={"max_execution_time": 10})

    @patch("django.db.connection.cursor")
    def test_execute_op_postgres(self, mock_cursor):
        execute_op(DEFAULT_POSTGRES_OP, "some_id")

        # correctly routes to postgres
        mock_cursor.assert_called_once()

    @patch("posthog.async_migrations.runner.attempt_migration_rollback")
    def test_process_error(self, _):
        sm = create_async_migration()
        process_error(sm, "some error")
        process_error(sm, "second error")

        sm.refresh_from_db()
        self.assertEqual(sm.status, MigrationStatus.Errored)
        self.assertGreater(sm.finished_at, datetime.now(UTC) - timedelta(hours=1))
        errors = AsyncMigrationError.objects.filter(async_migration=sm).order_by("created_at")
        self.assertEqual(errors.count(), 2)
        self.assertEqual(errors[0].description, "some error")
        self.assertEqual(errors[1].description, "second error")

    @patch("posthog.tasks.async_migrations.run_async_migration.delay")
    def test_trigger_migration(self, mock_run_async_migration):
        sm = create_async_migration()
        trigger_migration(sm)

        mock_run_async_migration.assert_called_once()

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_migration(self, mock_app_control_revoke):
        sm = create_async_migration()
        force_stop_migration(sm, rollback=False)

        sm.refresh_from_db()
        mock_app_control_revoke.assert_called_once()
        self.assertEqual(sm.status, MigrationStatus.Errored)
        errors = AsyncMigrationError.objects.filter(async_migration=sm)
        self.assertEqual(errors.count(), 1)
        self.assertEqual(errors[0].description, "Force stopped by user")

    def test_complete_migration(self):
        sm = create_async_migration()
        complete_migration(sm)

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertGreater(sm.finished_at, datetime.now(UTC) - timedelta(hours=1))

        self.assertEqual(sm.progress, 100)
        errors = AsyncMigrationError.objects.filter(async_migration=sm)
        self.assertEqual(errors.count(), 0)

    def test_execute_on_each_shard(self):
        execute_on_each_shard("SELECT 1")
        with self.assertRaises(Exception):
            execute_on_each_shard("SELECT fail")
