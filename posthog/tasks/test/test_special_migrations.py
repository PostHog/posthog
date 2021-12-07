from typing import Any, Dict
from unittest.mock import patch

import pytest
from celery.result import AsyncResult

from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.special_migrations.examples.test import Migration
from posthog.special_migrations.runner import run_special_migration_next_op
from posthog.special_migrations.setup import get_special_migration_definition
from posthog.special_migrations.test.util import create_special_migration
from posthog.tasks.special_migrations import CeleryTaskState, check_special_migration_health
from posthog.test.base import BaseTest

TEST_MIGRATION_DESCRIPTION = Migration().description
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
def run_special_migration_mock(migration_name, _) -> TaskMock:
    run_special_migration_next_op(migration_name)
    return TaskMock()


class TestSpecialMigrations(BaseTest):
    def setUp(self) -> None:
        create_special_migration(name="test", description=TEST_MIGRATION_DESCRIPTION)
        return super().setUp()

    @pytest.mark.ee
    @patch.object(AsyncResult, "state", CeleryTaskState.Started)
    @patch("posthog.celery.app.control.inspect", side_effect=inspect_mock)
    @patch("posthog.tasks.special_migrations.run_special_migration.delay", side_effect=run_special_migration_mock)
    def test_check_special_migration_health_during_resumable_op(self, _, __) -> None:
        sm = SpecialMigration.objects.get(name="test")
        sm.status = MigrationStatus.Running
        sm.save()

        run_special_migration_next_op("test", sm, run_all=False)
        run_special_migration_next_op("test", sm, run_all=False)
        run_special_migration_next_op("test", sm, run_all=False)

        sm.refresh_from_db()
        self.assertTrue(get_special_migration_definition("test").operations[sm.current_operation_index].resumable)

        check_special_migration_health()

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.CompletedSuccessfully)
        self.assertEqual(sm.current_operation_index, 4)
        self.assertEqual(sm.progress, 100)

    @pytest.mark.ee
    @patch.object(AsyncResult, "state", CeleryTaskState.Started)
    @patch("posthog.celery.app.control.inspect", side_effect=inspect_mock)
    @patch("posthog.tasks.special_migrations.run_special_migration.delay", side_effect=run_special_migration_mock)
    def test_check_special_migration_health_during_non_resumable_op(self, _, __) -> None:
        sm = SpecialMigration.objects.get(name="test")
        sm.status = MigrationStatus.Running
        sm.save()

        run_special_migration_next_op("test", sm, run_all=False)

        sm.refresh_from_db()
        self.assertFalse(get_special_migration_definition("test").operations[sm.current_operation_index].resumable)

        check_special_migration_health()

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.RolledBack)
