import csv
import datetime as dt
import io
from typing import TypedDict
from unittest import mock
from uuid import UUID, uuid4

import pytest
from asgiref.sync import sync_to_async
from boto3 import resource
from botocore.client import Config
from django.conf import settings
from django.test import override_settings
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute
from posthog.models import (
    BatchExport,
    BatchExportDestination,
    BatchExportRun,
    BatchExportSchedule,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    build_s3_url,
    insert_into_s3_activity,
)


@pytest.mark.parametrize(
    "inputs,expected",
    [
        (
            {
                "bucket": "my-test-bucket",
                "region": "us-east-1",
                "key_template": "posthog-events/events_{partition_id}.csv",
                "partition_id": "{_partition_id}",
            },
            "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.csv",
        ),
        (
            {
                "bucket": "my-test-bucket",
                "region": "us-east-1",
                "key_template": "posthog-{table_name}/{table_name}_{partition_id}.csv",
                "partition_id": "{_partition_id}",
                "table_name": "events",
            },
            "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.csv",
        ),
        (
            {
                "bucket": "my-test-bucket-2",
                "region": "eu-west-1",
                "key_template": "events.parquet",
            },
            "https://s3.eu-west-1.amazonaws.com/my-test-bucket-2/events.parquet",
        ),
    ],
)
def test_build_s3_url(inputs, expected):
    """Test the build_s3_url utility function used in the S3BatchExport workflow.

    We mock the TEST and DEBUG variables as we have some test logic that we are not interested in
    for this test, as we are interested in asserting production behavior!
    """
    result = build_s3_url(is_debug_or_test=False, **inputs)
    assert result == expected


@override_settings(TEST=False, DEBUG=False)
@pytest.mark.asyncio
async def test_insert_into_s3_activity(activity_environment):
    """Test the insert_into_s3_activity part of the S3BatchExport workflow.

    We mock calls to the ClickHouse client and assert the queries sent to it.
    """
    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-20 15:00:00"
    team_id = 2
    file_format = "Parquet"

    insert_inputs = S3InsertInputs(
        bucket_name="my-test-bucket",
        region="us-east-1",
        key_template="posthog-{table_name}/{table_name}_{partition_id}.parquet",
        team_id=team_id,
        file_format=file_format,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )

    expected_s3_url = "https://s3.us-east-1.amazonaws.com/my-test-bucket/posthog-events/events_{_partition_id}.parquet"

    expected_fetch_row_query = """
    SELECT count(*)
    FROM events
    WHERE
        timestamp >= toDateTime({data_interval_start}, 'UTC')
        AND timestamp < toDateTime({data_interval_end}, 'UTC')
        AND team_id = {team_id}
    """

    # Excuse the whitespace magic. I have to make indentation match for the assert_awaited_once_with call to pass.
    expected_execute_row_query = """
    INSERT INTO FUNCTION s3({path},  {file_format})\n    \n    \n    SELECT *
    FROM events
    WHERE
        timestamp >= toDateTime({data_interval_start}, 'UTC')
        AND timestamp < toDateTime({data_interval_end}, 'UTC')
        AND team_id = {team_id}
    """
    with (
        mock.patch("aiochclient.ChClient.fetchrow") as fetch_row,
        mock.patch("aiochclient.ChClient.execute") as execute,
    ):
        await activity_environment.run(insert_into_s3_activity, insert_inputs)

        expected_data_interval_start = dt.datetime.fromisoformat(data_interval_start).strftime("%Y-%m-%d %H:%M:%S")
        expected_data_interval_end = dt.datetime.fromisoformat(data_interval_end).strftime("%Y-%m-%d %H:%M:%S")
        fetch_row.assert_awaited_once_with(
            expected_fetch_row_query,
            params={
                "team_id": team_id,
                "data_interval_start": expected_data_interval_start,
                "data_interval_end": expected_data_interval_end,
            },
        )
        execute.assert_awaited_once_with(
            expected_execute_row_query,
            params={
                "aws_access_key_id": None,
                "aws_secret_access_key": None,
                "path": expected_s3_url,
                "file_format": file_format,
                "team_id": team_id,
                "data_interval_start": expected_data_interval_start,
                "data_interval_end": expected_data_interval_end,
            },
        )


TEST_ROOT_BUCKET = "test-batch-exports"


@pytest.fixture
def s3_bucket():
    """A testing S3 bucket resource."""
    s3 = resource(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    bucket = s3.Bucket(settings.OBJECT_STORAGE_BUCKET)

    yield bucket

    bucket.objects.filter(Prefix=TEST_ROOT_BUCKET).delete()


@pytest.fixture
def destination(team, s3_bucket):
    """A test BatchExportDestination targetting an S3 bucket.

    Technically, we are using a MinIO bucket. But the API is the same, so we also support it!
    """
    dest = BatchExportDestination.objects.create(
        name="my-s3-bucket",
        type="S3",
        team=team,
        config={
            "bucket_name": s3_bucket.name,
            "region": "us-east-1",
            "key_template": f"{TEST_ROOT_BUCKET}/posthog-{{table_name}}/events.csv",
            "batch_window_size": 3600,
            "aws_access_key_id": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )
    dest.save()

    yield dest

    dest.delete()


@pytest.fixture
def batch_export(destination, team):
    """A test BatchExport."""
    schedule = BatchExportSchedule.objects.create(team=team, paused=True)
    batch_export = BatchExport.objects.create(team=team, destination=destination, schedule=schedule)

    batch_export.save()

    yield batch_export

    batch_export.delete()


@pytest.fixture
def max_datetime():
    """An arbitrary date of reference for loading test events."""
    return dt.datetime(2023, 4, 25, 0, 0, 0, tzinfo=dt.timezone.utc)


class EventValues(TypedDict):
    """Events to be inserted for testing."""

    uuid: UUID
    event: str
    timestamp: dt.datetime
    person_id: UUID
    team_id: int


@pytest.fixture
def events_to_export(team, max_datetime):
    """Produce some test events for testing.

    These events will be yielded so that we can re-fetch them and assert their
    person_ids have been overriden.
    """
    all_test_events = []
    for n in range(1, 11):
        values: EventValues = {
            "uuid": uuid4(),
            "event": f"test-event-{n}",
            "timestamp": max_datetime - dt.timedelta(seconds=10 * n),
            "team_id": team.id,
            "person_id": uuid4(),
        }
        all_test_events.append(values)

    sync_execute("INSERT INTO sharded_events (uuid, event, timestamp, team_id, person_id) VALUES", all_test_events)

    yield all_test_events

    sync_execute("TRUNCATE TABLE sharded_events")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_s3_export_workflow_with_minio_bucket(
    s3_bucket, destination, team, organization, events_to_export, max_datetime, batch_export
):
    """Test the S3BatchExportWorkflow targetting a local MinIO bucket.

    The MinIO object-storage is part of the PostHog development stack. We are loading some events
    into ClickHouse and exporting them by running the S3BatchExportWorkflow.

    Once the Workflow finishes, we assert a new object exists in our bucket, that it matches our,
    key, and we read it's contents as a CSV to ensure all events we loaded are accounted for.
    """
    client = await Client.connect(
        f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}",
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    # To ensure these are populated in the db, we have to save them here.
    # These ignore comments are required. It's a bug in asigref fixed in newer versions.
    # See: https://github.com/django/asgiref/issues/281
    await sync_to_async(organization.save)()  # type:ignore
    await sync_to_async(team.save)()  # type:ignore
    await sync_to_async(destination.save)()  # type:ignore
    await sync_to_async(batch_export.save)()  # type:ignore

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=batch_export.team.id,
        batch_export_id=str(batch_export.id),
        data_interval_end=max_datetime.isoformat(),
        **batch_export.destination.config,
    )

    async with Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[S3BatchExportWorkflow],
        activities=[create_export_run, insert_into_s3_activity, update_export_run_status],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        await client.execute_workflow(
            S3BatchExportWorkflow.run,
            inputs,
            id=workflow_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        s3_objects = list(s3_bucket.objects.filter(Prefix=TEST_ROOT_BUCKET))
        assert len(s3_objects) == 1
        s3_object = s3_objects[0]

        assert s3_object.bucket_name == s3_bucket.name
        assert s3_object.key == f"{TEST_ROOT_BUCKET}/posthog-events/events.csv"

        file_obj = io.BytesIO()
        s3_bucket.download_fileobj(s3_object.key, file_obj)

        reader = csv.DictReader((line.decode() for line in file_obj.readlines()))
        for row in reader:
            event_id = row["id"]
            matching_event = [event for event in events_to_export if event.id == event_id][0]

            assert row["event"] == matching_event["event"]
            assert row["timestamp"] == matching_event["timestamp"]
            assert row["person_id"] == matching_event["person_id"]
            assert row["team_id"] == matching_event["team_id"]

        assert (
            await sync_to_async(BatchExportRun.objects.filter(team_id=destination.team.id).count)() == 1  # type:ignore
        )

        run = await sync_to_async(BatchExportRun.objects.filter(team_id=destination.team.id).first)()  # type:ignore
        assert run is not None
        assert run.status == "Completed"
        assert run.data_interval_end == max_datetime
