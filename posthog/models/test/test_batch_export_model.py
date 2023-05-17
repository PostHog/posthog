import csv
import datetime as dt
import io
import json
import time
from uuid import uuid4

from boto3 import resource
from botocore.client import Config
from django.db import connections
from freezegun import freeze_time
from temporalio.client import (
    ScheduleSpec,
    WorkflowExecutionDescription,
    WorkflowExecutionStatus,
)
from temporalio.service import RPCError

from posthog.clickhouse.client import sync_execute
from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    BatchExportSchedule,
)
from posthog.models.batch_export.batch_export import get_fernet
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)
from posthog.temporal.tests.test_s3_batch_export_workflow import EventValues
from posthog.test.base import (
    BaseTemporalTest,
    ClickhouseTestMixin,
    NonAtomicBaseTemporalTest,
)


class TestBatchExportDestination(NonAtomicBaseTemporalTest):
    """Test operations on BatchExportDestination models."""

    def test_encrypt_on_save(self):
        """Test config encrypted_keys are encrypted on create/save."""
        access_key_id = "my-very-valuable-access-key-id"
        secret_access_key = "my-very-valuable-secret-access-key-id"
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": "test-bucket",
                "region": "us-east-1",
                "key_template": "events.csv",
                "aws_access_key_id": access_key_id,
                "aws_secret_access_key": secret_access_key,
            },
        )
        self.assertNotEqual(destination.config["aws_access_key_id"], access_key_id)
        self.assertNotEqual(destination.config["aws_secret_access_key"], secret_access_key)

        destination.refresh_from_db()

        self.assertEqual(destination.config["aws_access_key_id"], access_key_id)
        self.assertEqual(destination.config["aws_secret_access_key"], secret_access_key)

        destination.save()

        self.assertNotEqual(destination.config["aws_access_key_id"], access_key_id)
        self.assertNotEqual(destination.config["aws_secret_access_key"], secret_access_key)

        conn = connections["default"]
        with conn.cursor() as cursor:
            # Let's check the actual database to ensure this is encrypted.
            cursor.execute("SELECT config FROM posthog_batchexportdestination WHERE id = %s", [str(destination.id)])
            config_row = cursor.fetchone()

            assert config_row is not None

            config = json.loads(config_row[0])

        self.assertNotEqual(config["aws_access_key_id"], access_key_id)
        self.assertNotEqual(config["aws_secret_access_key"], secret_access_key)

        fernet = get_fernet()
        self.assertEqual(fernet.decrypt(config["aws_access_key_id"].encode()), access_key_id.encode())
        self.assertEqual(fernet.decrypt(config["aws_secret_access_key"].encode()), secret_access_key.encode())


class TestBatchExportSchedule(BaseTemporalTest):
    """Test operations on BatchExportSchedule models."""

    def test_get_schedule_spec(self):
        """Test getting the ScheduleSpec from a BatchExportSchedule."""
        with freeze_time("2023-05-01 00:00:00"):
            start_at = dt.datetime.utcnow()
            end_at = start_at + dt.timedelta(hours=72)
            test_params = [
                (
                    {"cron_expressions": ["0 0 * * *"], "start_at": start_at, "end_at": end_at},
                    ScheduleSpec(cron_expressions=["0 0 * * *"], start_at=start_at, end_at=end_at),
                )
            ]

        for schedule_params, expected_spec in test_params:
            schedule = BatchExportSchedule.objects.create(team=self.team, **schedule_params)  # type:ignore

            spec = schedule.get_schedule_spec()
            self.assertEqual(spec, expected_spec)

    def test_get_batch_window_sizes(self):
        """Test getting the batch window sizes from a BatchExportSchedule."""
        test_params = [
            (
                [{"every": {"hours": 1}, "offset": {"minutes": 10}}],
                [{"hours": 1}],
            ),
            (
                [
                    {"every": {"hours": 1, "minutes": 5}, "offset": {"minutes": 10}},
                    {"every": {"hours": 2, "days": 1}, "offset": {"minutes": 10}},
                ],
                [{"hours": 1, "minutes": 5}, {"hours": 2, "days": 1}],
            ),
            (
                [
                    {"every": {"days": 1}, "offset": {"minutes": 10}},
                    {"every": {"days": 2}, "offset": {"minutes": 10}},
                ],
                [{"days": 1}, {"days": 2}],
            ),
            (
                [
                    {"every": {"days": 7}, "offset": {"minutes": 10}},
                ],
                [{"days": 7}],
            ),
        ]

        for intervals, expected_batch_window_sizes in test_params:
            schedule = BatchExportSchedule.objects.create(team=self.team, intervals=intervals)

            batch_window_sizes = schedule.get_batch_window_sizes()
            self.assertEqual(batch_window_sizes, expected_batch_window_sizes)

    def test_pause_and_unpause_schedule(self):
        """Test pausing and unpausing a Schedule."""
        schedule = BatchExportSchedule.objects.create(
            team=self.team, intervals=[{"every": {"seconds": 3600}}], paused=False
        )
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": "test-bucket",
                "region": "us-east-1",
                "key_template": "events.csv",
            },
        )

        with self.start_test_worker():
            BatchExport.objects.create(team=self.team, destination=destination, schedule=schedule)

            self.assertFalse(schedule.paused)

            schedule.pause(note="Paused for a test")
            self.assertTrue(schedule.paused)

            schedule_desc = self.describe_schedule(str(schedule.id))
            self.assertTrue(schedule_desc.schedule.state.paused)
            self.assertEqual(schedule_desc.schedule.state.note, "Paused for a test")

            with self.assertRaises(ValueError):
                schedule.pause()

            schedule.unpause(note="Unpaused for a test")
            self.assertFalse(schedule.paused)

            schedule_desc = self.describe_schedule(str(schedule.id))
            self.assertFalse(schedule_desc.schedule.state.paused)
            self.assertEqual(schedule_desc.schedule.state.note, "Unpaused for a test")

            with self.assertRaises(ValueError):
                schedule.unpause()


class TestBatchExport(BaseTemporalTest):
    """Test operations on BatchExport models."""

    def test_create_batch_export_schedule(self):
        """Test creation of a BatchExport Temporal Schedule."""
        schedule = BatchExportSchedule.objects.create(
            team=self.team, intervals=[{"every": {"seconds": 3600}}], paused=True
        )
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": "test-bucket",
                "region": "us-east-1",
                "key_template": "exports/posthog-{{table_name}}/events.csv",
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            },
        )

        with self.start_test_worker():
            batch_export = BatchExport.objects.create(team=self.team, destination=destination, schedule=schedule)
            schedule_desc = self.describe_schedule(str(batch_export.schedule.id))

        self.assertTrue(schedule_desc.schedule.state.paused)
        self.assertEqual(schedule_desc.schedule.action.id, str(batch_export.id))
        self.assertEqual(schedule_desc.schedule.action.retry_policy, batch_export.get_retry_policy())
        self.assertEqual(schedule_desc.schedule.action.execution_timeout, batch_export.execution_timeout)

        expected_search_attributes = {
            "DestinationId": [str(batch_export.destination.id)],
            "DestinationType": [batch_export.destination.type],
            "TeamId": [batch_export.schedule.team.id],
            "TeamName": [batch_export.schedule.team.name],
            "BatchExportId": [str(batch_export.id)],
        }
        self.assertEqual(schedule_desc.schedule.action.search_attributes, expected_search_attributes)

    def test_delete_batch_export_schedule(self):
        """Test deletion of a BatchExport Temporal Schedule."""
        schedule = BatchExportSchedule.objects.create(
            team=self.team, intervals=[{"every": {"seconds": 3600}}], paused=True
        )
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": "test-bucket",
                "region": "us-east-1",
                "key_template": "exports/posthog-{{table_name}}/events.csv",
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            },
        )

        with self.start_test_worker():
            batch_export = BatchExport.objects.create(team=self.team, destination=destination, schedule=schedule)

            schedule_desc = self.describe_schedule(str(batch_export.schedule.id))
            self.assertTrue(schedule_desc.schedule.state.paused)
            self.assertEqual(schedule_desc.schedule.action.id, str(batch_export.id))

            batch_export.delete_batch_export_schedule()

            with self.assertRaises(RPCError):
                schedule_desc = self.describe_schedule(str(batch_export.schedule.id))


class TestBatchExportExecution(NonAtomicBaseTemporalTest, ClickhouseTestMixin):
    """Tests related to executing a BatchExport."""

    bucket_root = "test-batch-exports-key"
    _bucket = None

    @property
    def bucket(self):
        if self._bucket is None:
            s3 = resource(
                "s3",
                endpoint_url=OBJECT_STORAGE_ENDPOINT,
                aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY_ID,
                aws_secret_access_key=OBJECT_STORAGE_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="us-east-1",
            )
            self._bucket = s3.Bucket(OBJECT_STORAGE_BUCKET)
        return self._bucket

    def tearDown(self):
        super().tearDown()
        self.bucket.objects.filter(Prefix=self.bucket_root).delete()

    def create_test_events(self, max_datetime=None) -> list[EventValues]:
        """Create some test events to export."""
        max_datetime = max_datetime or dt.datetime.utcnow()

        all_test_events = []
        for n in range(1, 11):
            values: EventValues = {
                "uuid": uuid4(),
                "event": f"test-event-{n}",
                "timestamp": max_datetime - dt.timedelta(seconds=10 * n),
                "team_id": self.team.id,
                "person_id": uuid4(),
            }
            all_test_events.append(values)

        sync_execute("INSERT INTO sharded_events (uuid, event, timestamp, team_id, person_id) VALUES", all_test_events)

        return all_test_events

    def assert_s3_object_events(self, s3_object, events):
        """Assert the events in an S3 Object match the given events.

        We download the given S3 Object, reading it assuming it's a CSV and compare it against events.
        There should be a matching event for each CSV row.
        """
        file_obj = io.BytesIO()
        self.bucket.download_fileobj(s3_object.key, file_obj)

        reader = csv.DictReader((line.decode() for line in file_obj.readlines()))
        for row in reader:
            event_id = row["uuid"]
            matching_event = [event for event in events if event["uuid"] == event_id][0]

            self.assertEqual(row["event"], matching_event["event"])
            self.assertEqual(row["timestamp"], matching_event["timestamp"])
            self.assertEqual(row["person_id"], matching_event["person_id"])
            self.assertEqual(row["team_id"], matching_event["team_id"])

    def test_trigger_batch_export(self):
        """Trigger a test BatchExport and check its output."""
        self.organization.save()
        self.team.save()

        max_datetime = dt.datetime.utcnow()
        test_events = self.create_test_events(max_datetime)

        schedule = BatchExportSchedule.objects.create(
            team=self.team, intervals=[{"every": {"seconds": 3600}}], paused=False
        )
        key_uuid = uuid4()
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": self.bucket.name,
                "region": "us-east-1",
                # We use a UUID here to ensure uniqueness in case the export is run multiple times.
                "key_template": f"{self.bucket_root}/{key_uuid}/posthog-{{table_name}}/events.csv",
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
                "data_interval_end": max_datetime.isoformat(),
            },
        )
        with self.start_test_worker():
            batch_export = BatchExport.objects.create(team=self.team, destination=destination, schedule=schedule)
            batch_export.save()

            batch_export.trigger()

            total = 0
            timeout = 15
            workflow: None | WorkflowExecutionDescription = None
            while workflow is None or workflow.status == WorkflowExecutionStatus.RUNNING:
                time.sleep(1)
                total += 1

                if total > timeout:
                    raise TimeoutError(f"Workflow didn't finish after {timeout} seconds")

                export_run = BatchExportRun.objects.filter(batch_export=batch_export).first()

                if export_run is None:
                    # This can take a few tries...
                    continue

                workflow = export_run.describe()

        self.assertEqual(workflow.status, WorkflowExecutionStatus.COMPLETED)

        s3_objects = list(self.bucket.objects.filter(Prefix=f"{self.bucket_root}/{key_uuid}"))
        self.assertEqual(len(s3_objects), 1)
        s3_object = s3_objects[0]

        self.assertEqual(s3_object.bucket_name, self.bucket.name)
        self.assertEqual(s3_object.key, f"{self.bucket_root}/{key_uuid}/posthog-events/events.csv")

        self.assert_s3_object_events(s3_object, test_events)

    def test_backfill_batch_export(self):
        """Backfill a test BatchExport and check its output."""
        self.organization.save()
        self.team.save()

        start_at = dt.datetime(2023, 5, 1, 12, 0, 0, tzinfo=dt.timezone.utc)

        # Until time travel is discovered, these two sets of events will happen before the schedule is created (now).
        # However, notice that the schedule would have picked them up if it had been running after 2023-05-01 12:00:00.
        # In particular, they would have been included in the 2023-05-01 12:00:00-2023-05-01 13:00:00 and
        # 2023-05-01 13:00:00-2023-05-01 14:00:00 batches.
        test_events_1 = self.create_test_events(start_at + dt.timedelta(hours=1))
        test_events_2 = self.create_test_events(start_at + dt.timedelta(hours=2))

        schedule = BatchExportSchedule.objects.create(
            team=self.team, paused=False, intervals=[{"every": {"hours": 1}}], start_at=start_at
        )
        key_uuid = uuid4()
        destination = BatchExportDestination.objects.create(
            team=self.team,
            name="test-s3-destination",
            type="S3",
            config={
                "bucket_name": self.bucket.name,
                "region": "us-east-1",
                # We use a UUID here to ensure uniqueness in case the export test is run multiple times.
                "key_template": f"{self.bucket_root}/{key_uuid}/{{datetime}}/posthog-{{table_name}}/events.csv",
                "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
                "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
            },
        )

        with self.start_test_worker():
            batch_export = BatchExport.objects.create(team=self.team, destination=destination, schedule=schedule)
            batch_export.save()

            batch_export.backfill(start_at=start_at, end_at=start_at + dt.timedelta(hours=2))

            total = 0
            timeout = 30
            both_done = False
            workflows = []
            while both_done is False:
                time.sleep(1)
                total += 1

                if total > timeout:
                    raise TimeoutError(f"Workflow didn't finish after {timeout} seconds")

                export_runs = BatchExportRun.objects.filter(batch_export=batch_export).all()

                if not export_runs or len(export_runs) < 2:
                    continue

                workflows = [export_runs[0].describe(), export_runs[1].describe()]

                both_done = not any(workflow.status == WorkflowExecutionStatus.RUNNING for workflow in workflows)

        self.assertTrue(all(workflow.status == WorkflowExecutionStatus.COMPLETED for workflow in workflows))

        s3_objects = list(self.bucket.objects.filter(Prefix=f"{self.bucket_root}/{key_uuid}"))
        self.assertEqual(len(s3_objects), 2)

        keys_to_events = {
            f"{self.bucket_root}/{key_uuid}/{(start_at + dt.timedelta(hours=1)).isoformat()}/posthog-events/events.csv": test_events_1,
            f"{self.bucket_root}/{key_uuid}/{(start_at + dt.timedelta(hours=2)).isoformat()}/posthog-events/events.csv": test_events_2,
        }
        for s3_object in s3_objects:
            self.assertEqual(s3_object.bucket_name, self.bucket.name)
            self.assertIn(s3_object.key, keys_to_events.keys())
            events = keys_to_events.pop(s3_object.key)
            self.assert_s3_object_events(s3_object, events)
