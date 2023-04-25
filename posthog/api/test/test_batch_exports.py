from asgiref.sync import async_to_sync
from rest_framework import status
from temporalio.client import Client
from temporalio.service import RPCError

from posthog.api.batch_exports import get_temporal_client
from posthog.models import ExportDestination, ExportSchedule
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestBatchExportsAPI(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()
        self.temporal: Client = get_temporal_client()

    def test_create_export_destination(self):
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
            "primary_schedule": {"start_at": "2023-04-26T00:00:00Z", "intervals": [{"every": "43200", "offset": "0"}]},
        }
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(ExportDestination.objects.count(), 1)

        data = response.json()
        self.assertEqual(data["name"], destination_data["name"])
        self.assertEqual(data["type"], destination_data["type"])
        self.assertEqual(data["config"], destination_data["config"])
        self.assertEqual(
            data["primary_schedule"]["start_at"],
            # Apparently, 'destination_data["primary_schedule"]' is not indexable.
            # Maybe a mypy bug, as of writing, PostHog still uses mypy<1.0.
            destination_data["primary_schedule"]["start_at"],  # type: ignore
        )  # TODO: check the schedule is correct

    def test_get_export_destination(self):
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
            "primary_schedule": {"start_at": "2023-04-26T00:00:00Z", "intervals": [{"every": "43200", "offset": "0"}]},
        }
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportDestination.objects.count(), 1)

        response = self.client.get(f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}")

        data = response.json()
        self.assertEqual(data["name"], destination_data["name"])
        self.assertEqual(data["type"], destination_data["type"])
        self.assertEqual(data["config"], destination_data["config"])
        self.assertEqual(
            data["primary_schedule"]["start_at"],
            # Apparently, 'destination_data["primary_schedule"]' is not indexable.
            # Maybe a mypy bug, as of writing, PostHog still uses mypy<1.0.
            destination_data["primary_schedule"]["start_at"],  # type: ignore
        )  # TODO: check the schedule is correct

    def test_create_export_schedule(self):
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
            "primary_schedule": {"start_at": "2023-04-26T00:00:00.000Z", "intervals": [{"every": "43200", "offset": "0"}]},
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        manual_schedule_data = {
            "start_at": "2021-01-01T00:00:00+00:00",
        }

        schedule_response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}/schedules", manual_schedule_data
        )

        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportSchedule.objects.count(), 2)

        export_schedule = ExportSchedule.objects.get(id=schedule_response.json()["id"])

        self.assertEqual(export_schedule.start_at.isoformat(), manual_schedule_data["start_at"])

        handle = self.temporal.get_schedule_handle(
            str(export_schedule.id),
        )
        temporal_schedule = async_to_sync(handle.describe)()

        self.assertEqual(temporal_schedule.id, str(export_schedule.id))

        # Clean-up the schedule
        async_to_sync(handle.delete)()

    def test_delete_export_schedule(self):
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
            "primary_schedule": {"start_at": "2023-04-26T00:00:00.000Z", "intervals": [{"every": "43200", "offset": "0"}]},
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        schedule_name = "one-off-schedule"
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

        export_schedule = ExportSchedule.objects.get(id=schedule_response.json()["id"])

        handle = self.temporal.get_schedule_handle(
            str(export_schedule.id),
        )

        response = self.client.delete(
            f"/api/projects/{self.team.id}/batch_exports/{response.json()['id']}/schedules/{export_schedule.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        try:
            ExportSchedule.objects.get(id=export_schedule.id)
            assert False
        except ExportSchedule.DoesNotExist:
            assert True

        with self.assertRaisesRegex(RPCError, "schedule not found"):
            async_to_sync(handle.describe)()
