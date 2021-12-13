from datetime import datetime
from os import stat
from unittest.mock import patch

import pytz
from django.utils import timezone
from rest_framework import status

from posthog.models.special_migration import MigrationStatus, SpecialMigration
from posthog.models.team import Team
from posthog.test.base import APIBaseTest


def create_special_migration(
    name="test1",
    description="my desc",
    posthog_min_version="1.0.0",
    posthog_max_version="100000.0.0",
    status=MigrationStatus.NotStarted,
    last_error="",
):
    return SpecialMigration.objects.create(
        name=name,
        description=description,
        posthog_min_version=posthog_min_version,
        posthog_max_version=posthog_max_version,
        status=status,
        last_error=last_error,
    )


class TestSpecialMigration(APIBaseTest):
    def setUp(self):
        self.user.is_staff = True
        self.user.save()
        return super().setUp()

    def test_get_special_migrations_without_staff_status(self):

        response = self.client.get(f"/api/special_migrations/").json()
        self.assertEqual(response["count"], 0)

        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/special_migrations/").json()

        self.assertEqual(response["code"], "permission_denied")
        self.assertEqual(response["detail"], "You are not a staff user, contact your instance admin.")

    def test_get_special_migrations(self):
        create_special_migration()
        create_special_migration(name="test2")

        response = self.client.get(f"/api/special_migrations/").json()

        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][0]["name"], "test1")
        self.assertEqual(response["results"][1]["name"], "test2")

    @patch("posthog.tasks.special_migrations.run_special_migration.delay")
    def test_trigger_endpoint(self, mock_run_special_migration):
        sm1 = create_special_migration()
        # sm2 = create_special_migration(name="test2")

        response = self.client.post(f"/api/special_migrations/{sm1.id}/trigger").json()
        sm1.refresh_from_db()

        mock_run_special_migration.assert_called_once()
        self.assertEqual(response["success"], True)
        self.assertEqual(sm1.status, MigrationStatus.Starting)

    @patch("posthog.tasks.special_migrations.run_special_migration.delay")
    def test_trigger_with_another_migration_running(self, mock_run_special_migration):
        sm1 = create_special_migration()
        create_special_migration(name="test2", status=MigrationStatus.Running)

        response = self.client.post(f"/api/special_migrations/{sm1.id}/trigger").json()
        mock_run_special_migration.assert_not_called()
        self.assertEqual(response["success"], False)
        self.assertEqual(response["error"], "No more than 1 special migration can run at once.")

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_endpoint(self, mock_run_special_migration):
        sm1 = create_special_migration(status=MigrationStatus.Running)

        response = self.client.post(f"/api/special_migrations/{sm1.id}/force_stop").json()
        sm1.refresh_from_db()

        mock_run_special_migration.assert_called_once()
        self.assertEqual(response["success"], True)
        self.assertEqual(sm1.status, MigrationStatus.Errored)
        self.assertEqual(sm1.last_error, "Force stopped by user")

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_endpoint_non_running_migration(self, mock_run_special_migration):
        sm1 = create_special_migration(status=MigrationStatus.RolledBack)

        response = self.client.post(f"/api/special_migrations/{sm1.id}/force_stop").json()
        sm1.refresh_from_db()

        mock_run_special_migration.assert_not_called()
        self.assertEqual(response["success"], False)
        self.assertEqual(response["error"], "Can't stop a migration that isn't running.")

        # didn't change
        self.assertEqual(sm1.status, MigrationStatus.RolledBack)

    def test_force_rollback_endpoint(self):
        sm1 = create_special_migration(status=MigrationStatus.CompletedSuccessfully)

        response = self.client.post(f"/api/special_migrations/{sm1.id}/force_rollback").json()

        self.assertEqual(response["success"], True)

    def test_force_rollback_endpoint_migration_not_complete(self):
        sm1 = create_special_migration(status=MigrationStatus.Running)

        response = self.client.post(f"/api/special_migrations/{sm1.id}/force_rollback").json()

        self.assertEqual(response["success"], False)
        self.assertEqual(response["error"], "Can't force rollback a migration that did not complete successfully.")
