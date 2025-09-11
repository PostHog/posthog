from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.async_migrations.definition import AsyncMigrationDefinition
from posthog.models.async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus


def create_async_migration(
    name="test1",
    description="my desc",
    posthog_min_version="1.0.0",
    posthog_max_version="100000.0.0",
    status=MigrationStatus.NotStarted,
):
    return AsyncMigration.objects.create(
        name=name,
        description=description,
        posthog_min_version=posthog_min_version,
        posthog_max_version=posthog_max_version,
        status=status,
    )


class TestAsyncMigration(APIBaseTest):
    def setUp(self):
        self.user.is_staff = True
        self.user.save()
        return super().setUp()

    def test_get_async_migrations_without_staff_status(self):
        response = self.client.get(f"/api/async_migrations/").json()
        self.assertEqual(response["count"], 0)

        self.user.is_staff = False
        self.user.save()

        response = self.client.get(f"/api/async_migrations/").json()

        self.assertEqual(response["code"], "permission_denied")
        self.assertEqual(response["detail"], "You are not a staff user, contact your instance admin.")

    def test_get_async_migrations(self):
        create_async_migration(name="0002_events_sample_by")
        create_async_migration(name="0003_fill_person_distinct_id2")

        response = self.client.get(f"/api/async_migrations/").json()

        self.assertEqual(len(response["results"]), 2)
        self.assertEqual(response["results"][0]["name"], "0002_events_sample_by")
        self.assertEqual(response["results"][1]["name"], "0003_fill_person_distinct_id2")

    @patch("posthog.tasks.async_migrations.run_async_migration.delay")
    def test_trigger_endpoint(self, mock_run_async_migration):
        sm1 = create_async_migration()

        response = self.client.post(
            f"/api/async_migrations/{sm1.id}/trigger",
            {"parameters": {"SOME_KEY": 1234}},
        ).json()
        sm1.refresh_from_db()

        mock_run_async_migration.assert_called_once()
        self.assertEqual(response["success"], True)
        self.assertEqual(sm1.status, MigrationStatus.Starting)
        self.assertEqual(sm1.parameters, {"SOME_KEY": 1234})

    @patch("posthog.tasks.async_migrations.run_async_migration.delay")
    def test_trigger_with_another_migration_running(self, mock_run_async_migration):
        sm1 = create_async_migration()
        create_async_migration(name="test2", status=MigrationStatus.Running)

        response = self.client.post(f"/api/async_migrations/{sm1.id}/trigger").json()
        mock_run_async_migration.assert_not_called()
        self.assertEqual(response["success"], False)
        self.assertEqual(response["error"], "No more than 1 async migration can run at once.")

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_endpoint(self, mock_run_async_migration):
        sm1 = create_async_migration(status=MigrationStatus.Running)

        response = self.client.post(f"/api/async_migrations/{sm1.id}/force_stop_without_rollback").json()
        sm1.refresh_from_db()

        mock_run_async_migration.assert_called_once()
        self.assertEqual(response["success"], True)
        self.assertEqual(sm1.status, MigrationStatus.Errored)
        errors = AsyncMigrationError.objects.filter(async_migration=sm1)
        self.assertEqual(errors.count(), 1)
        self.assertEqual(errors[0].description, "Force stopped by user")

    @patch("posthog.celery.app.control.revoke")
    def test_force_stop_endpoint_non_running_migration(self, mock_run_async_migration):
        sm1 = create_async_migration(status=MigrationStatus.RolledBack)

        response = self.client.post(f"/api/async_migrations/{sm1.id}/force_stop").json()
        sm1.refresh_from_db()

        mock_run_async_migration.assert_not_called()
        self.assertEqual(response["success"], False)
        self.assertEqual(response["error"], "Can't stop a migration that isn't running.")

        # didn't change
        self.assertEqual(sm1.status, MigrationStatus.RolledBack)

    @patch("posthog.async_migrations.runner.get_async_migration_definition")
    def test_force_rollback_endpoint(self, mock_get_migration_definition):
        mock_get_migration_definition.return_value = AsyncMigrationDefinition(name="foo")
        sm1 = create_async_migration(status=MigrationStatus.CompletedSuccessfully)

        response = self.client.post(f"/api/async_migrations/{sm1.id}/force_rollback").json()

        mock_get_migration_definition.assert_called_once()
        self.assertEqual(response["success"], True)

    def test_force_rollback_endpoint_migration_not_complete(self):
        sm1 = create_async_migration(status=MigrationStatus.Running)

        response = self.client.post(f"/api/async_migrations/{sm1.id}/force_rollback").json()

        self.assertEqual(response["success"], False)
        self.assertEqual(
            response["error"],
            "Can't force rollback a migration that did not complete successfully.",
        )
