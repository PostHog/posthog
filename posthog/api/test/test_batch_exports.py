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
            "primary_schedule": {
                "name": "test-schedule",
                "cron_expressions": ["0 0 * * *"],
            },
        }
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ExportDestination.objects.count(), 1)

        self.assertEqual(response.data["name"], destination_data["name"])
        self.assertEqual(response.data["type"], destination_data["type"])
        self.assertEqual(response.data["config"], destination_data["config"])
        self.assertEqual(
            response.data["primary_schedule"]["cron_expressions"],
            destination_data["primary_schedule"]["cron_expressions"],
        )

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
            "primary_schedule": {
                "name": "test-schedule",
                "cron_expressions": ["0 0 * * *"],
            },
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        schedule_name = "one-off-schedule"
        manual_schedule_data = {
            "name": schedule_name,
            "start_at": "2021-01-01T00:00:00+00:00",
        }

        schedule_response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/{response.data['id']}/schedules", manual_schedule_data
        )

        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED, schedule_response.data)
        self.assertEqual(ExportSchedule.objects.count(), 2)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]

        self.assertEqual(export_schedule.name, manual_schedule_data["name"])
        self.assertEqual(export_schedule.start_at.isoformat(), manual_schedule_data["start_at"])

        handle = self.temporal.get_schedule_handle(
            export_schedule.id.__str__(),
        )
        temporal_schedule = async_to_sync(handle.describe)()

        self.assertEqual(temporal_schedule.id, export_schedule.id.__str__())

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
            "primary_schedule": {
                "name": "test-schedule",
                "cron_expressions": ["0 0 * * *"],
            },
        }

        self.assertEqual(ExportDestination.objects.count(), 0)
        self.assertEqual(ExportSchedule.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", destination_data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(ExportDestination.objects.count(), 1)
        self.assertEqual(ExportSchedule.objects.count(), 1)

        schedule_name = "one-off-schedule"
        manual_schedule_data = {
            "name": schedule_name,
            "start_at": "2021-01-01T00:00:00+00:00",
            "cron_expressions": ["0 0 * * *"],
        }

        schedule_response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/{response.data['id']}/schedules", manual_schedule_data
        )

        self.assertEqual(schedule_response.status_code, status.HTTP_201_CREATED, schedule_response.data)
        self.assertEqual(ExportSchedule.objects.count(), 2)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]

        handle = self.temporal.get_schedule_handle(
            export_schedule.id.__str__(),
        )

        response = self.client.delete(
            f"/api/projects/{self.team.id}/batch_exports/{response.data['id']}/schedules/{export_schedule.id}"
        )

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT, response.data)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)
        assert not export_schedule.exists()

        async_to_sync(handle.describe)()

        with self.assertRaisesRegex(RPCError, "schedule not found"):
            async_to_sync(handle.describe)()
