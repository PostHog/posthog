import datetime as dt
from uuid import uuid4

from rest_framework import status
from temporalio.client import ScheduleRange
from temporalio.service import RPCError

from posthog.api.test.test_team import create_team
from posthog.models import (
    BatchExportDestination,
    BatchExportRun,
)
from posthog.test.base import APIBaseTest, BaseTemporalTest


class TestBatchBatchExportsAPI(BaseTemporalTest, APIBaseTest):
    """Test the REST API for BatchExports."""

    def test_create_batch_export_destination(self):
        """Test creating an BatchExportDestionation for S3."""
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        self.assertEqual(BatchExportDestination.objects.count(), 0)

        response = self.client.post(f"/api/projects/{self.team.id}/batch_export_destinations", destination_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())
        self.assertEqual(BatchExportDestination.objects.count(), 1)

        data = response.json()
        self.assertEqual(data["name"], destination_data["name"])
        self.assertEqual(data["type"], destination_data["type"])

        expected_config = {
            k: v
            for k, v in destination_data["config"].items()  # type: ignore
            if k not in ("aws_access_key_id", "aws_secret_access_key")
        }
        self.assertEqual(data["config"], expected_config)

    def test_list_batch_export_destination(self):
        """Test listing BatchExportDestionations"""
        destination_names = [f"my-production-s3-bucket-{n}" for n in range(3)]
        destination_data = {
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        for name in destination_names:
            destination_data["name"] = name
            response = self.client.post(f"/api/projects/{self.team.id}/batch_export_destinations", destination_data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Create a BatchExportDestination for a different team to assert it's not included in the response.
        team = create_team(organization=self.organization)
        destination_data["name"] = "destination-from-different-team"
        response = self.client.post(f"/api/projects/{team.id}/batch_export_destinations", destination_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())

        response = self.client.get(f"/api/projects/{self.team.id}/batch_export_destinations")
        self.assertEqual(response.status_code, status.HTTP_200_OK, msg=response.json())

        data = response.json()
        self.assertEqual(data["count"], 3)

        expected_config = {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
        }

        for destination in data["results"]:
            self.assertNotEqual(destination["name"], "destination-from-different-team")
            self.assertIn(destination["name"], destination_names)
            self.assertEqual(destination["type"], "S3")
            self.assertEqual(destination["config"], expected_config)

    def test_create_batch_export_with_interval_schedule(self):
        """Test creating a BatchExport.

        When creating a BatchExport, we should create a corresponding Schedule in Temporal as described
        by the associated BatchExportSchedule model. In this test we assert this Schedule is created in
        Temporal.
        """
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "intervals": [{"every": {"seconds": 3600}}],
            "paused": False,
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())

        data = response.json()

        expected_config = {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
        }
        self.assertEqual(data["destination"]["name"], destination_data["name"])
        self.assertEqual(data["destination"]["type"], destination_data["type"])
        self.assertEqual(data["destination"]["config"], expected_config)
        self.assertEqual(data["schedule"]["cron_expressions"], [])
        self.assertEqual(data["schedule"]["calendars"], [])
        self.assertEqual(data["schedule"]["intervals"], [{"every": {"seconds": 3600}}])
        self.assertEqual(data["schedule"]["skip"], [])

        schedule_desc = self.describe_schedule(data["schedule"]["id"])
        self.assertEqual(schedule_desc.id, data["schedule"]["id"])
        self.assertEqual(len(schedule_desc.schedule.spec.calendars), 0)
        self.assertEqual(len(schedule_desc.schedule.spec.intervals), 1)

        schedule_interval_spec = schedule_desc.schedule.spec.intervals[0]
        self.assertEqual(schedule_interval_spec.every, dt.timedelta(seconds=3600))

    def test_create_batch_export_with_cron_schedule(self):
        """Test creating a BatchExport.

        When creating a BatchExport, we should create a corresponding Schedule in Temporal as described
        by the associated BatchExportSchedule model. In this test we assert this Schedule is created in
        Temporal.
        """
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "paused": True,
            "intervals": [{"every": {"seconds": 3600}}],
            "cron_expressions": ["0 0 * * *"],
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())

        data = response.json()

        expected_config = {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
        }
        self.assertEqual(data["destination"]["name"], destination_data["name"])
        self.assertEqual(data["destination"]["type"], destination_data["type"])
        self.assertEqual(data["destination"]["config"], expected_config)
        self.assertEqual(data["schedule"]["cron_expressions"], schedule_data["cron_expressions"])
        self.assertEqual(data["schedule"]["calendars"], [])
        self.assertEqual(data["schedule"]["skip"], [])

        schedule_desc = self.describe_schedule(data["schedule"]["id"])
        self.assertEqual(schedule_desc.id, data["schedule"]["id"])

        # When passing a Cron expression, Temporal ✨ magically ✨ transforms it to a ScheduleCalendarSpec
        self.assertEqual(len(schedule_desc.schedule.spec.calendars), 1)
        spec = schedule_desc.schedule.spec.calendars[0]
        self.assertEqual(spec.second[0], ScheduleRange(start=0, end=0, step=0))
        self.assertEqual(spec.minute[0], ScheduleRange(start=0, end=0, step=0))
        self.assertEqual(spec.hour[0], ScheduleRange(start=0, end=0, step=0))
        self.assertEqual(spec.day_of_month[0], ScheduleRange(start=1, end=31, step=0))
        self.assertEqual(spec.day_of_week[0], ScheduleRange(start=0, end=6, step=0))
        self.assertEqual(spec.month[0], ScheduleRange(start=1, end=12, step=0))

        self.assertEqual(schedule_desc.schedule.state.paused, True)

    def test_create_batch_export_with_calendar_schedule(self):
        """Test creating a BatchExport with a calendar schedule.

        When creating a BatchExport, we should create a corresponding Schedule in Temporal as described
        by the associated BatchExportSchedule model. In this test we assert this Schedule is created in
        Temporal.
        """
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "paused": True,
            "intervals": [{"every": {"seconds": 3600}}],
            # At every 30-minute mark between the hours of 1 and 10.
            "calendars": [{"hour": [{"start": 1, "end": 10, "step": 0}], "minute": [{"start": 30}]}],
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())

        data = response.json()

        expected_config = {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "key_template": "posthog-events/{table_name}.csv",
        }
        self.assertEqual(data["destination"]["name"], destination_data["name"])
        self.assertEqual(data["destination"]["type"], destination_data["type"])
        self.assertEqual(data["destination"]["config"], expected_config)
        self.assertEqual(data["schedule"]["cron_expressions"], [])
        self.assertEqual(data["schedule"]["calendars"], schedule_data["calendars"])
        self.assertEqual(data["schedule"]["skip"], [])

        schedule_desc = self.describe_schedule(data["schedule"]["id"])
        self.assertEqual(schedule_desc.id, data["schedule"]["id"])

        self.assertEqual(len(schedule_desc.schedule.spec.calendars), 1)
        spec = schedule_desc.schedule.spec.calendars[0]
        self.assertEqual(spec.second[0], ScheduleRange(start=0, end=0, step=0))
        self.assertEqual(spec.minute[0], ScheduleRange(start=30, end=0, step=0))
        self.assertEqual(spec.hour[0], ScheduleRange(start=1, end=10, step=0))
        self.assertEqual(spec.day_of_month[0], ScheduleRange(start=1, end=31, step=0))
        self.assertEqual(spec.day_of_week[0], ScheduleRange(start=0, end=6, step=0))
        self.assertEqual(spec.month[0], ScheduleRange(start=1, end=12, step=0))

        self.assertEqual(schedule_desc.schedule.state.paused, True)

    def test_pause_and_unpause_batch_export(self):
        """Test pausing and unpausing a BatchExport."""
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "paused": False,
            "intervals": [{"every": {"seconds": 3600}}],
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())

            batch_export = response.json()
            self.assertEqual(batch_export["schedule"]["paused"], False)
            schedule_desc = self.describe_schedule(batch_export["schedule"]["id"])
            self.assertEqual(schedule_desc.schedule.state.paused, False)

            batch_export_id = batch_export["id"]

            response = self.client.patch(f"/api/projects/{self.team.id}/batch_exports/{batch_export_id}/pause")
            self.assertEqual(response.status_code, status.HTTP_200_OK, msg=response.json())

            data = response.json()
            self.assertEqual(data["schedule"]["paused"], True)
            schedule_desc = self.describe_schedule(data["schedule"]["id"])
            self.assertEqual(schedule_desc.schedule.state.paused, True)

            response = self.client.patch(f"/api/projects/{self.team.id}/batch_exports/{batch_export_id}/pause")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=response.json())

            response = self.client.patch(f"/api/projects/{self.team.id}/batch_exports/{batch_export_id}/unpause")
            self.assertEqual(response.status_code, status.HTTP_200_OK, msg=response.json())

            data = response.json()
            self.assertEqual(data["schedule"]["paused"], False)
            schedule_desc = self.describe_schedule(data["schedule"]["id"])
            self.assertEqual(schedule_desc.schedule.state.paused, False)

            response = self.client.patch(f"/api/projects/{self.team.id}/batch_exports/{batch_export_id}/unpause")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=response.json())

    def test_delete_batch_export(self):
        """Test deleting a BatchExport."""
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "paused": True,
            "intervals": [{"every": {"seconds": 3600}}],
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())
            batch_export = response.json()
            batch_export_id = batch_export["id"]

            response = self.client.delete(
                f"/api/projects/{self.team.id}/batch_exports/{batch_export_id}", batch_export_data
            )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with self.assertRaises(RPCError):
            self.describe_schedule(batch_export_id)

    def test_retrieve_batch_export(self):
        """Test retrieving a BatchExport."""
        destination_data = {
            "name": "my-production-s3-bucket-destination",
            "type": "S3",
            "config": {
                "bucket_name": "my-production-s3-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/{table_name}.csv",
                "aws_access_key_id": "abc123",
                "aws_secret_access_key": "secret",
            },
        }
        schedule_data = {
            "paused": True,
            "intervals": [{"every": {"seconds": 3600}}],
        }
        batch_export_data = {
            "destination": destination_data,
            "schedule": schedule_data,
        }
        with self.start_test_worker():
            response = self.client.post(f"/api/projects/{self.team.id}/batch_exports", batch_export_data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED, msg=response.json())
            batch_export = response.json()
            batch_export_id = batch_export["id"]

            data_interval_start = dt.datetime.utcnow().isoformat()
            data_interval_end = dt.datetime.utcnow().isoformat()

            # Create a few runs so that we have something to return
            for n in range(10):
                BatchExportRun.objects.create(
                    team_id=self.team.id,
                    run_id=str(uuid4()),
                    workflow_id=f"batch-export-run-{n}",
                    batch_export_id=batch_export_id,
                    data_interval_start=data_interval_start,
                    data_interval_end=data_interval_end,
                )

            response = self.client.get(f"/api/projects/{self.team.id}/batch_exports")
        data = response.json()

        self.assertEqual(data["count"], 1)

        batch_export = data["results"][0]
        self.assertEqual(batch_export["id"], batch_export_id)
        self.assertEqual(batch_export["destination"]["type"], "S3")
        self.assertEqual(batch_export["schedule"]["paused"], True)
        self.assertEqual(len(batch_export["runs"]), 10)
        self.assertTrue(all(run["data_interval_start"] == f"{data_interval_start}Z" for run in batch_export["runs"]))
        self.assertTrue(all(run["data_interval_end"] == f"{data_interval_end}Z" for run in batch_export["runs"]))
