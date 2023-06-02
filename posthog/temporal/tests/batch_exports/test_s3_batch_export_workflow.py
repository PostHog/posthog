import json
from random import randint
from typing import TypedDict
from uuid import uuid4
import boto3

from aiochclient import ChClient
import pytest
from django.conf import settings
from django.test import Client as HttpClient
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker
from posthog.batch_exports.service import acreate_batch_export, afetch_batch_export_runs
from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team

from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    insert_into_s3_activity,
)

bucket_name = ""

TEST_ROOT_BUCKET = "test-batch-exports"


class EventValues(TypedDict):
    """Events to be inserted for testing."""

    uuid: str
    event: str
    timestamp: str
    person_id: str
    team_id: int
    properties: str


async def insert_events(client: ChClient, events: list[EventValues]):
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


def teardown_module(module):
    """
    Delete the random S3 bucket created for testing. We need to also delete all the
    objects in the bucket before we can delete the bucket itself.
    """
    s3_client = boto3.client(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    response = s3_client.list_objects_v2(Bucket=bucket_name)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])

    s3_client.delete_bucket(Bucket=bucket_name)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_insert_into_s3_activity_puts_data_into_s3(activity_environment):
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


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_with_minio_bucket(client: HttpClient):
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
            "key_template": "posthog-events/{table_name}.csv",
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
            "person_id": str(uuid4()),
            "team_id": team.pk,
            "properties": json.dumps({"$browser": "Chrome", "$os": "Mac OS X"}),
        },
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 14:30:00.000000",
            "person_id": str(uuid4()),
            "team_id": team.pk,
            "properties": json.dumps({"$browser": "Chrome", "$os": "Mac OS X"}),
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
