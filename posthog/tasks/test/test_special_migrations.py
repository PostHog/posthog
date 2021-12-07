from datetime import datetime
from time import sleep
from unittest.mock import patch

import pytest
from celery.result import AsyncResult
from django.db import connection

from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.utils import UUIDT
from posthog.special_migrations.examples.test import Migration
from posthog.special_migrations.runner import (
    attempt_migration_rollback,
    run_special_migration_next_op,
    start_special_migration,
)
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
    def active():
        return {"some_node_id": [{"id": MOCK_CELERY_TASK_ID}]}


def inspect_mock():
    return InspectorMock()


# mock to make us run the migration in sync fashion
def run_special_migration_mock(migration_name, _):
    run_special_migration_next_op(migration_name)
    return TaskMock()


class TestSpecialMigrations(BaseTest):
    def setUp(self):
        create_special_migration(name="test", description=TEST_MIGRATION_DESCRIPTION)
        return super().setUp()

    @pytest.mark.ee
    @patch.object(AsyncResult, "state", CeleryTaskState.Started)
    @patch("posthog.celery.app.control.inspect", side_effect=inspect_mock)
    @patch("posthog.tasks.special_migrations.run_special_migration.delay", side_effect=run_special_migration_mock)
    def test_check_special_migration_health_during_resumable_op(self, _, __):
        sm = SpecialMigration.objects.get(name="test")
        sm.status = MigrationStatus.Running
        # sm.celery_task_id = "some_task_id"
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
    def test_check_special_migration_health_during_non_resumable_op(self, _, __):
        sm = SpecialMigration.objects.get(name="test")
        sm.status = MigrationStatus.Running
        sm.save()

        run_special_migration_next_op("test", sm, run_all=False)

        sm.refresh_from_db()
        self.assertFalse(get_special_migration_definition("test").operations[sm.current_operation_index].resumable)

        check_special_migration_health()

        sm.refresh_from_db()

        self.assertEqual(sm.status, MigrationStatus.RolledBack)
