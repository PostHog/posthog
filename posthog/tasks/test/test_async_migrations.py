from typing import Any
from unittest.mock import patch

import pytest
from celery import states
from celery.result import AsyncResult

from posthog.async_migrations.examples.test_migration import Migration
from posthog.async_migrations.runner import run_async_migration_next_op, run_async_migration_operations
from posthog.async_migrations.test.util import create_async_migration
from posthog.models.async_migration import AsyncMigration, MigrationStatus
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.async_migrations import check_async_migration_health
from posthog.test.base import BaseTest

TEST_MIGRATION_DESCRIPTION = Migration("TEST_MIGRATION").description
MOCK_CELERY_TASK_ID = "some_task_id"


class TaskMock:
    id = MOCK_CELERY_TASK_ID


class InspectorMock:
    @staticmethod
    def active() -> Any:
        return {"some_node_id": [{"id": MOCK_CELERY_TASK_ID}]}


def inspect_mock() -> InspectorMock:
    return InspectorMock()


# mock to make us run the migration in sync fashion
def run_async_migration_mock(migration_name: str, _: Any) -> TaskMock:
    run_async_migration_operations(migration_name)
    return TaskMock()


class TestAsyncMigrations(BaseTest):
    def setUp(self) -> None:
        create_async_migration(name="test_migration", description=TEST_MIGRATION_DESCRIPTION)
        return super().setUp()

    @pytest.mark.ee
    @patch.object(AsyncResult, "state", states.STARTED)
    @patch("posthog.celery.app.control.inspect", side_effect=inspect_mock)
    @patch("posthog.tasks.async_migrations.run_async_migration.delay", side_effect=run_async_migration_mock)
    def test_check_async_migration_health_during_resumable_op(self, _: Any, __: Any) -> None:
        """
        Mocks celery tasks and tests that `check_async_migration_health` works as expected
        if we find that the process crashed before the migration completed.
        Given the op is resumable, we would expect check_async_migration_health to re-trigger the migration
        from where we left off
        """
        set_instance_setting("ASYNC_MIGRATIONS_AUTO_CONTINUE", True)

        sm = AsyncMigration.objects.get(name="test_migration")
        sm.status = MigrationStatus.Running
        sm.save()

        run_async_migration_next_op("test_migration", sm)
        run_async_migration_next_op("test_migration", sm)
        run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()

        check_async_migration_health()

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.current_operation_index, 7)
        self.assertEqual(sm.progress, 100)

    @pytest.mark.ee
    @patch.object(AsyncResult, "state", states.STARTED)
    @patch("posthog.celery.app.control.inspect", side_effect=inspect_mock)
    @patch("posthog.tasks.async_migrations.run_async_migration.delay", side_effect=run_async_migration_mock)
    def test_check_async_migration_health_during_non_resumable_op(self, _: Any, __: Any) -> None:
        """
        Same as above, but now we find a non-resumbale op.
        Given the op is not resumable, we would expect check_async_migration_health to *not* re-trigger the migration
        and instead roll it back.
        """
        set_instance_setting("ASYNC_MIGRATIONS_AUTO_CONTINUE", False)
        set_instance_setting("ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", False)

        sm = AsyncMigration.objects.get(name="test_migration")
        sm.status = MigrationStatus.Running
        sm.save()

        run_async_migration_next_op("test_migration", sm)

        sm.refresh_from_db()

        check_async_migration_health()

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.RolledBack)
