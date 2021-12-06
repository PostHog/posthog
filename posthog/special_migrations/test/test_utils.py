from datetime import datetime
from unittest.mock import patch

import pytest

from posthog.constants import AnalyticsDBMS
from posthog.models.special_migration import MigrationStatus
from posthog.models.team import Team
from posthog.special_migrations.setup import SPECIAL_MIGRATIONS_EXAMPLE_MODULE_PATH
from posthog.special_migrations.test.util import create_special_migration
from posthog.special_migrations.utils import (
    execute_op,
    force_stop_migration,
    mark_migration_as_successful,
    process_error,
    trigger_migration,
)
from posthog.test.base import BaseTest


class TestUtils(BaseTest):
    @pytest.mark.ee
    @patch("ee.clickhouse.client.sync_execute")
    def test_execute_op_clickhouse(self, mock_sync_execute):
        execute_op(AnalyticsDBMS.CLICKHOUSE, "SELECT 1", 10, "some_id")

        # correctly routes to ch
        mock_sync_execute.assert_called_once_with("/* some_id */ SELECT 1", settings={"max_execution_time": 10})

    @patch("django.db.connection.cursor")
    def test_execute_op_postgres(self, mock_cursor):
        execute_op(AnalyticsDBMS.POSTGRES, "SELECT 1", 10, "some_id")

        # correctly routes to postgres
        mock_cursor.assert_called_once()

    @patch("posthog.special_migrations.runner.attempt_migration_rollback")
    def test_process_error(self, _):
        sm = create_special_migration()
        process_error(sm, "some error")

        sm.refresh_from_db()
        self.assertEqual(sm.status, MigrationStatus.Errored)
        self.assertEqual(sm.last_error, "some error")
        self.assertEqual(sm.finished_at.day, datetime.now().day)

    @patch("posthog.tasks.special_migrations.run_special_migration.delay")
    def test_trigger_migration(self, mock_run_special_migration):
        sm = create_special_migration()
        trigger_migration(sm)

        mock_run_special_migration.assert_called_once()

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_migration(self, mock_app_control_revoke):
        sm = create_special_migration()
        force_stop_migration(sm)

        sm.refresh_from_db()
        mock_app_control_revoke.assert_called_once()
        self.assertEqual(sm.status, MigrationStatus.Errored)
        self.assertEqual(sm.last_error, "Force stopped by user")

    def test_mark_migration_as_successful(self):

        sm = create_special_migration()
        mark_migration_as_successful(sm)

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.finished_at.day, datetime.now().day)
        self.assertEqual(sm.last_error, "")
        self.assertEqual(sm.progress, 100)
