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

    def test_create_export_schedule(self):
        """Test creating an ExportSchedule with a destination."""
        schedule_name = "test-schedule"
        data = {
            "name": schedule_name,
            "destination": {
                "type": "S3",
                "name": "my-production-s3-bucket-destination",
                "config": {
                    "bucket_name": "my-production-s3-bucket",
                    "region": "us-east-1",
                    "file_name_prefix": "posthog-events/",
                    "batch_window_size": 3600,
                    "aws_access_key_id": "abc123",
                    "aws_secret_access_key": "secret",
                },
            },
        }
        self.assertEqual(ExportSchedule.objects.count(), 0)
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/@current/batch_exports", data=data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ExportSchedule.objects.count(), 1)
        self.assertEqual(ExportDestination.objects.count(), 1)

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)[0]

        handle = self.temporal.get_schedule_handle(
            export_schedule.name,
        )
        temporal_schedule = async_to_sync(handle.describe)()

        self.assertEqual(temporal_schedule.id, schedule_name)

        # Clean-up the schedule
        async_to_sync(handle.delete)()

    def test_delete_export_schedule(self):
        """Test deleting an ExportSchedule with a destination."""
        schedule_name = "test-schedule"
        data = {
            "name": schedule_name,
            "destination": {
                "type": "S3",
                "name": "my-production-s3-bucket-destination",
                "config": {
                    "bucket_name": "my-production-s3-bucket",
                    "region": "us-east-1",
                    "key_template": "posthog-events/{table_name}.csv",
                    "batch_window_size": 3600,
                    "aws_access_key_id": "abc123",
                    "aws_secret_access_key": "secret",
                },
            },
        }
        self.assertEqual(ExportSchedule.objects.count(), 0)
        self.assertEqual(ExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/@current/batch_exports", data=data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        export_schedules = ExportSchedule.objects.filter(name=schedule_name)
        assert export_schedules.exists()

        export_schedule = export_schedules[0]
        handle = self.temporal.get_schedule_handle(
            export_schedule.name,
        )

        response = self.client.delete(f"/api/projects/@current/batch_exports/{export_schedule.id}")

        export_schedule = ExportSchedule.objects.filter(name=schedule_name)
        assert not export_schedule.exists()

        with self.assertRaisesRegex(RPCError, "schedule not found"):
            async_to_sync(handle.describe)()
