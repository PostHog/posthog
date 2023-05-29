import csv
import io
import json
from random import randint
from typing import TypedDict
from uuid import uuid4
import boto3

from aiochclient import ChClient
import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import (
    BatchExportRun,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    insert_into_s3_activity,
)
import logging

bucket_name = ""


def setup_module(module):
    """
    Create a random S3 bucket for testing.
    """
    global bucket_name
    bucket_name = f"{TEST_ROOT_BUCKET}-{str(uuid4())}"

    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    s3_client.create_bucket(Bucket=bucket_name)

    logging.getLogger().setLevel(logging.DEBUG)


@pytest.mark.asyncio
async def test_insert_into_s3_activity_puts_data_into_s3(activity_environment):
    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-20 14:30:00.000000",
            "person_id": str(uuid4()),
            "team_id": team_id,
            "properties": json.dumps({"$browser": "Chrome", "$os": "Mac OS X"}),
        },
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 14:30:00.000000",
            "person_id": str(uuid4()),
            "team_id": team_id,
            "properties": json.dumps({"$browser": "Chrome", "$os": "Mac OS X"}),
        },
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=client,
        events=events,
    )

    # Make a random string to prefix the S3 keys with. This allows us to ensure
    # isolation of the test, and also to check that the data is being written.
    prefix = str(uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        key_template=f"{prefix}",
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    await activity_environment.run(insert_into_s3_activity, insert_inputs)

    # Check that the data was written to S3.
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    # List the objects in the bucket with the prefix.
    objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)

    # Check that there is only one object.
    assert len(objects.get("Contents", [])) == 1

    # Get the object.
    key = objects["Contents"][0].get("Key")
    assert key
    object = s3_client.get_object(Bucket=bucket_name, Key=key)
    data = object["Body"].read()

    # Check that the data is correct.
    json_data = [json.loads(line) for line in data.decode("utf-8").split("\n") if line]
    # Pull out the fields we inserted only
    json_data = [
        {
            "uuid": event["uuid"],
            "event": event["event"],
            "timestamp": event["timestamp"],
            "properties": event["properties"],
            "person_id": event["person_id"],
            "team_id": int(event["team_id"]),
        }
        for event in json_data
    ]
    assert json_data == events


TEST_ROOT_BUCKET = "test-batch-exports"


class EventValues(TypedDict):
    """Events to be inserted for testing."""

    uuid: str
    event: str
    timestamp: str
    person_id: str
    team_id: int
    properties: str


async def insert_events(client, events: list[EventValues]):
    """Insert some events into the sharded_events table."""
    await client.execute(
        f"""
        INSERT INTO `sharded_events` (
            uuid,
            event,
            timestamp,
            person_id,
            team_id,
            properties
        )
        VALUES
        """,
        *[
            (
                event["uuid"],
                event["event"],
                event["timestamp"],
                event["person_id"],
                event["team_id"],
                event["properties"],
            )
            for event in events
        ],
        json=False,
    )


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
    await organization.save()  # type:ignore
    await team.save()  # type:ignore
    await destination.save()  # type:ignore
    await batch_export.save()  # type:ignore

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
            await sync_to_async(BatchExportRun.objects.filter(batch_export_id=batch_export.pk).count)()
            == 1  # type:ignore
        )

        run = await sync_to_async(BatchExportRun.objects.filter(batch_export_id=batch_export.pk).first)()  # type:ignore
        assert run is not None
        assert run.status == "Completed"
        assert run.data_interval_end == max_datetime
