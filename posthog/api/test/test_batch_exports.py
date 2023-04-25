import logging
from itertools import count

from asgiref.sync import async_to_sync
from rest_framework import status
from temporalio.client import Client
from temporalio.service import RPCError

from posthog.models import ExportDestination, ExportSchedule
from posthog.temporal.client import sync_connect
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestBatchExportsAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.temporal: Client = sync_connect()
        self.id_generator = count()
        self.schedules_to_tear_down = []

    def tearDown(self):
        """Tear-down test cases by cleaning up any Temporal Schedules created during the test."""
        for schedule_name in self.schedules_to_tear_down:
            handle = self.temporal.get_schedule_handle(schedule_name)
            try:
                async_to_sync(handle.delete)()
            except RPCError:
                # Assume this was expected as we are tearing down, but don't fail silently.
                logging.warn("Schedule %s has already been deleted, ignoring.", schedule_name)
                continue

    def describe_schedule(self, schedule_id: str):
        """Return the description of a Temporal Schedule with the given id."""
        handle = self.temporal.get_schedule_handle(schedule_id)
        temporal_schedule = async_to_sync(handle.describe)()
        return temporal_schedule

    def get_test_schedule_name(self, prefix: str = "test-schedule") -> str:
        """Return a Temporal Schedule test name after appending it for tear-down after used.

        To construct a Temporal Schedule test name, we append a strictly increasing numeric id to the given
        prefix.
        """
        schedule_name = f"{prefix}-{next(self.id_generator)}"
        self.schedules_to_tear_down.append(schedule_name)
        return schedule_name

    def test_create_export_destination(self):
        """Test creating an ExportDestionation for S3.

        As we are passing Schedule information, this should also create a Schedule.
        """
        schedule_name = self.get_test_schedule_name()

        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "batch_window_size": 3600,
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
            "schedule": {
                "name": schedule_name,
                "cron_expressions": ["0 0 * * *"],
            },
        }
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportDestination.objects.count(), 1)

        data = response.json()
        self.assertEqual(data["name"], destination_data["name"])
        self.assertEqual(data["type"], destination_data["type"])
        self.assertEqual(data["config"], destination_data["config"])
        self.assertEqual(
            data["schedule"]["cron_expressions"],
            # Apparently, 'destination_data["schedule"]' is not indexable.
            # Maybe a mypy bug, as of writing, PostHog still uses mypy<1.0.
            destination_data["schedule"]["cron_expressions"],  # type: ignore
        )

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]
        temporal_schedule = self.describe_schedule(str(export_schedule.id))
        self.assertEqual(temporal_schedule.id, str(export_schedule.id))

    def test_create_export_schedule(self):
        """Test creating an ExportSchedule.

        An ExportSchedule is created in supposed to be created in Temporal too.
        """
        schedule_name = self.get_test_schedule_name()

        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "batch_window_size": 3600,
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
            "schedule": {
                "name": schedule_name,
                "cron_expressions": ["0 0 * * *"],
            },
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        schedule_name = self.get_test_schedule_name("one-off-schedule")
        manual_schedule_data = {
            "name": schedule_name,
            "start_at": "2021-01-01T00:00:00+00:00",
        }

        schedule_response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}/schedules", manual_schedule_data
        )

        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportSchedule.objects.count(), 2)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]

        self.assertEqual(export_schedule.name, manual_schedule_data["name"])
        self.assertEqual(export_schedule.start_at.isoformat(), manual_schedule_data["start_at"])

        temporal_schedule = self.describe_schedule(str(export_schedule.id))
        self.assertEqual(temporal_schedule.id, str(export_schedule.id))

    def test_delete_export_schedule(self):
        """Test deleting an ExportSchedule.

        This call should clean-up state from both the database and Temporal.
        """
        schedule_name = self.get_test_schedule_name()

        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "batch_window_size": 3600,
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
            "schedule": {
                "name": schedule_name,
                "cron_expressions": ["0 0 * * *"],
            },
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        schedule_name = self.get_test_schedule_name("one-off-schedule")
        manual_schedule_data = {
            "name": schedule_name,
            "start_at": "2021-01-01T00:00:00+00:00",
            "cron_expressions": ["0 0 * * *"],
        }

        schedule_response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}/schedules", manual_schedule_data
        )

        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportSchedule.objects.count(), 2)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]

        handle = self.temporal.get_schedule_handle(
            str(export_schedule.id),
        )

        response = self.client.delete(
            f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}/schedules/{export_schedule.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        post_export_schedule = ExportSchedule.objects.filter(name=schedule_name)
        assert not post_export_schedule.exists()

        with self.assertRaisesRegex(RPCError, "schedule not found"):
            async_to_sync(handle.describe)()
