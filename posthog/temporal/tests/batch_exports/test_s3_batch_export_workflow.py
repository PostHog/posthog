import functools
import json
from random import randint
from typing import TypedDict
from unittest import mock
from uuid import uuid4

import boto3
import pytest
from aiochclient import ChClient
from django.conf import settings
from django.test import Client as HttpClient
from django.test import override_settings
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.batch_exports.service import acreate_batch_export, afetch_batch_export_runs
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    insert_into_s3_activity,
)

TEST_ROOT_BUCKET = "test-batch-exports"


"""Events to be inserted for testing."""
EventValues = TypedDict(
    "EventValues",
    {
        "uuid": str,
        "event": str,
        "_timestamp": str,
        "timestamp": str,
        "created_at": str,
        "distinct_id": str,
        "person_id": str,
        "person_properties": dict | None,
        "team_id": int,
        "properties": dict | None,
        "elements_chain": str,
    },
)


async def insert_events(client: ChClient, events: list[EventValues]):
    """Insert some events into the sharded_events table."""
    await client.execute(
        f"""
        INSERT INTO `sharded_events` (
            uuid,
            event,
            timestamp,
            _timestamp,
            person_id,
            team_id,
            properties,
            elements_chain,

            distinct_id,
            created_at,
            person_properties
        )
        VALUES
        """,
        *[
            (
                event["uuid"],
                event["event"],
                event["timestamp"],
                event["_timestamp"],
                event["person_id"],
                event["team_id"],
                json.dumps(event["properties"]) if isinstance(event["properties"], dict) else event["properties"],
                event["elements_chain"],
                event["distinct_id"],
                event["created_at"],
                json.dumps(event["person_properties"])
                if isinstance(event["person_properties"], dict)
                else event["person_properties"],
            )
            for event in events
        ],
        json=False,
    )


create_test_client = functools.partial(boto3.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name() -> str:
    """Name for a test S3 bucket."""
    return f"{TEST_ROOT_BUCKET}-{str(uuid4())}"


@pytest.fixture
def s3_client(bucket_name):
    """Manage a testing S3 client to interact with a testing S3 bucket.

    Yields the test S3 client after creating a testing S3 bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    s3_client = create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    s3_client.create_bucket(Bucket=bucket_name)

    yield s3_client

    response = s3_client.list_objects_v2(Bucket=bucket_name)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])

    s3_client.delete_bucket(Bucket=bucket_name)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_s3_activity_puts_data_into_s3(bucket_name, s3_client, activity_environment):
    """
    Test that the insert_into_s3_activity function puts data into S3. We do not
    assume anything about the Django models, and instead just check that the
    data is in S3.
    """

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

    # Create enough events to ensure we span more than 5MB, the smallest
    # multipart chunk size for multipart uploads to S3.
    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "created_at": "2023-04-20 14:30:00.000000",
            "distinct_id": str(uuid4()),
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team_id,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "elements_chain": "this that and the other",
        }
        # NOTE: we have to do a lot here, otherwise we do not trigger a
        # multipart upload, and the minimum part chunk size is 5MB.
        for i in range(10000)
    ]

    events += [
        # Insert an events with an empty string in `properties` and
        # `person_properties` to ensure that we handle empty strings correctly.
        EventValues(
            {
                "uuid": str(uuid4()),
                "event": "test",
                "_timestamp": "2023-04-20 14:29:00",
                "timestamp": "2023-04-20 14:29:00.000000",
                "created_at": "2023-04-20 14:29:00.000000",
                "distinct_id": str(uuid4()),
                "person_id": str(uuid4()),
                "person_properties": None,
                "team_id": team_id,
                "properties": None,
                "elements_chain": "",
            }
        )
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=client,
        events=events,
    )

    # Insert some events before the hour and after the hour, as well as some
    # events from another team to ensure that we only export the events from
    # the team that the batch export is for.
    other_team_id = team_id + 1
    await insert_events(
        client=client,
        events=[
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 13:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 15:30:00",
                "_timestamp": "2023-04-20 13:30:00",
                "created_at": "2023-04-20 13:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-20 14:30:00",
                "_timestamp": "2023-04-20 14:30:00",
                "created_at": "2023-04-20 14:30:00.000000",
                "person_id": str(uuid4()),
                "distinct_id": str(uuid4()),
                "team_id": other_team_id,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            },
        ],
    )

    # Make a random string to prefix the S3 keys with. This allows us to ensure
    # isolation of the test, and also to check that the data is being written.
    prefix = str(uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        with mock.patch("posthog.temporal.workflows.s3_batch_export.boto3.client", side_effect=create_test_client):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    # Check that the data was written to S3.
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

    json_data.sort(key=lambda x: x["timestamp"])

    # Remove team_id, _timestamp from events
    expected_events = [{k: v for k, v in event.items() if k not in ["team_id", "_timestamp"]} for event in events]
    expected_events.sort(key=lambda x: x["timestamp"])

    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert json_data[0] == expected_events[0]
    assert json_data == expected_events


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_with_minio_bucket(client: HttpClient, s3_client):
    """
    Test that the whole workflow not just the activity works. It should update
    the batch export run status to completed, as well as updating the record
    count.
    """
    ch_client = ChClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "my-production-s3-bucket",
            "region": "us-east-1",
            "prefix": "posthog-events/",
            "batch_window_size": 3600,
            "aws_access_key_id": "abc123",
            "aws_secret_access_key": "secret",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    organization = await acreate_organization("test")
    team = await acreate_team(organization=organization)
    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-20 14:30:00.000000",
            "created_at": "2023-04-20 14:30:00.000000",
            "_timestamp": "2023-04-20 14:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 14:30:00.000000",
            "created_at": "2023-04-25 14:30:00.000000",
            "_timestamp": "2023-04-25 14:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=ch_client,
        events=events,
    )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[create_export_run, insert_into_s3_activity, update_export_run_status],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch("posthog.temporal.workflows.s3_batch_export.boto3.client", side_effect=create_test_client):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Completed"
