import asyncio
import datetime as dt
import functools
import gzip
import itertools
import json
import os
from random import randint
from unittest import mock
from uuid import uuid4

import boto3
import botocore.exceptions
import brotli
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import Client as HttpClient
from django.test import override_settings
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.api.test.test_organization import acreate_organization
from posthog.api.test.test_team import acreate_team
from posthog.temporal.client import connect
from posthog.temporal.tests.batch_exports.base import (
    EventValues,
    amaterialize,
    insert_events,
    to_isoformat,
)
from posthog.temporal.tests.batch_exports.fixtures import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
from posthog.temporal.workflows.clickhouse import ClickHouseClient
from posthog.temporal.workflows.s3_batch_export import (
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    get_s3_key,
    insert_into_s3_activity,
)

TEST_ROOT_BUCKET = "test-batch-exports"


def check_valid_credentials() -> bool:
    """Check if there are valid AWS credentials in the environment."""
    sts = boto3.client("sts")
    try:
        sts.get_caller_identity()
    except botocore.exceptions.ClientError:
        return False
    else:
        return True


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


def assert_events_in_s3(
    s3_client, bucket_name, key_prefix, events, compression: str | None = None, exclude_events: list[str] | None = None
):
    """Assert provided events written to JSON in key_prefix in S3 bucket_name."""
    # List the objects in the bucket with the prefix.
    objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    # Check that there is only one object.
    assert len(objects.get("Contents", [])) == 1

    # Get the object.
    key = objects["Contents"][0].get("Key")
    assert key
    object = s3_client.get_object(Bucket=bucket_name, Key=key)
    data = object["Body"].read()

    # Check that the data is correct.
    match compression:
        case "gzip":
            data = gzip.decompress(data)
        case "brotli":
            data = brotli.decompress(data)
        case _:
            pass

    json_data = [json.loads(line) for line in data.decode("utf-8").split("\n") if line]
    # Pull out the fields we inserted only

    json_data.sort(key=lambda x: x["timestamp"])

    # Remove team_id, _timestamp from events
    if exclude_events is None:
        exclude_events = []

    def to_expected_event(event):
        mapping_functions = {
            "timestamp": to_isoformat,
            "inserted_at": to_isoformat,
            "created_at": to_isoformat,
        }
        return {
            k: mapping_functions.get(k, lambda x: x)(v) for k, v in event.items() if k not in ["team_id", "_timestamp"]
        }

    expected_events = list(map(to_expected_event, (event for event in events if event["event"] not in exclude_events)))

    expected_events.sort(key=lambda x: x["timestamp"] if x["timestamp"] is not None else 0)

    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert json_data[0] == expected_events[0]
    assert json_data == expected_events


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "compression,exclude_events",
    itertools.product([None, "gzip", "brotli"], [None, ["test-exclude"]]),
)
async def test_insert_into_s3_activity_puts_data_into_s3(
    bucket_name, s3_client, activity_environment, compression, exclude_events
):
    """Test that the insert_into_s3_activity function puts data into S3."""

    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-25 15:00:00"

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    # Add a materialized column such that we can verify that it is NOT included
    # in the export.
    await amaterialize("events", "$browser")

    # Create enough events to ensure we span more than 5MB, the smallest
    # multipart chunk size for multipart uploads to S3.
    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "_timestamp": "2023-04-20 14:30:00",
            "timestamp": f"2023-04-20 14:30:00.{i:06d}",
            "inserted_at": f"2023-04-20 14:30:00.{i:06d}",
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
                "event": "test-exclude",
                "_timestamp": "2023-04-20 14:29:00",
                "timestamp": "2023-04-20 14:29:00.000000",
                "inserted_at": "2023-04-20 14:30:00.000000",
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
                "inserted_at": "2023-04-20 13:30:00.000000",
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
                "inserted_at": "2023-04-20 13:30:00.000000",
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
                "inserted_at": "2023-04-20 14:30:00.000000",
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
        compression=compression,
        exclude_events=exclude_events,
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        with mock.patch("posthog.temporal.workflows.s3_batch_export.boto3.client", side_effect=create_test_client):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert_events_in_s3(s3_client, bucket_name, prefix, events, compression, exclude_events)


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interval,compression,exclude_events",
    itertools.product(["hour", "day"], [None, "gzip", "brotli"], [None, ["test-exclude"]]),
)
async def test_s3_export_workflow_with_minio_bucket(
    client: HttpClient, s3_client, bucket_name, interval, compression, exclude_events
):
    """Test S3 Export Workflow end-to-end by using a local MinIO bucket instead of S3.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.
    """
    prefix = f"posthog-events-{str(uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
            "exclude_events": exclude_events,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
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
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": "2023-04-25 13:30:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
        {
            "uuid": str(uuid4()),
            "event": "test-exclude",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": "2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
    ]

    if interval == "day":
        # Add an event outside the hour range but within the day range to ensure it's exported too.
        events_outside_hour: list[EventValues] = [
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-25 00:30:00.000000",
                "created_at": "2023-04-25 00:30:00.000000",
                "inserted_at": "2023-04-25 00:30:00.000000",
                "_timestamp": "2023-04-25 00:30:00",
                "person_id": str(uuid4()),
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "team_id": team.pk,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "distinct_id": str(uuid4()),
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            }
        ]
        events += events_outside_hour

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

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
        interval=interval,
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
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(s3_client, bucket_name, prefix, events, compression, exclude_events)


@pytest.mark.skipif(
    "S3_TEST_BUCKET" not in os.environ or not check_valid_credentials(),
    reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
)
@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "interval,compression,encryption,exclude_events",
    itertools.product(["hour", "day"], [None, "gzip", "brotli"], [None, "AES256", "aws:kms"], [None, ["test-exclude"]]),
)
async def test_s3_export_workflow_with_s3_bucket(interval, compression, encryption, exclude_events):
    """Test S3 Export Workflow end-to-end by using an S3 bucket.

    The S3_TEST_BUCKET environment variable is used to set the name of the bucket for this test.
    This test will be skipped if no valid AWS credentials exist, or if the S3_TEST_BUCKET environment
    variable is not set.

    The workflow should update the batch export run status to completed and produce the expected
    records to the S3 bucket.
    """
    bucket_name = os.getenv("S3_TEST_BUCKET")
    kms_key_id = os.getenv("S3_TEST_KMS_KEY_ID")
    prefix = f"posthog-events-{str(uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
            "exclude_events": exclude_events,
            "encryption": encryption,
            "kms_key_id": kms_key_id if encryption == "aws:kms" else None,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
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
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": "2023-04-25 13:30:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
        {
            "uuid": str(uuid4()),
            "event": "test-exclude",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": "2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
    ]

    if interval == "day":
        # Add an event outside the hour range but within the day range to ensure it's exported too.
        events_outside_hour: list[EventValues] = [
            {
                "uuid": str(uuid4()),
                "event": "test",
                "timestamp": "2023-04-25 00:30:00.000000",
                "created_at": "2023-04-25 00:30:00.000000",
                "inserted_at": "2023-04-25 00:30:00.000000",
                "_timestamp": "2023-04-25 00:30:00",
                "person_id": str(uuid4()),
                "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "team_id": team.pk,
                "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
                "distinct_id": str(uuid4()),
                "elements_chain": "this is a comman, separated, list, of css selectors(?)",
            }
        ]
        events += events_outside_hour

    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

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
        interval=interval,
        **batch_export.destination.config,
    )

    s3_client = boto3.client("s3")

    def create_s3_client(*args, **kwargs):
        """Mock function to return an already initialized S3 client."""
        return s3_client

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[create_export_run, insert_into_s3_activity, update_export_run_status],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch("posthog.temporal.workflows.s3_batch_export.boto3.client", side_effect=create_s3_client):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(s3_client, bucket_name, prefix, events, compression, exclude_events)


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("compression", [None, "gzip"])
async def test_s3_export_workflow_with_minio_bucket_and_a_lot_of_data(
    client: HttpClient, s3_client, bucket_name, compression
):
    """Test the full S3 workflow targetting a MinIO bucket.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.
    """
    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    prefix = f"posthog-events-{str(uuid4())}-{{year}}-{{month}}-{{day}}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
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
            "event": f"test-{i}",
            "timestamp": f"2023-04-25 13:30:00.{i:06}",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": f"2023-04-25 13:30:00.{i:06}",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        }
        for i in range(1000000)
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
                    execution_timeout=dt.timedelta(seconds=360),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(s3_client, bucket_name, prefix.format(year=2023, month="04", day="25"), events, compression)


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"])
async def test_s3_export_workflow_defaults_to_timestamp_on_null_inserted_at(
    client: HttpClient, s3_client, bucket_name, compression
):
    """Test the full S3 workflow targetting a MinIO bucket.

    In this scenario we assert that when inserted_at is NULL, we default to _timestamp.
    This scenario is relevant values inserted before the migration happened.
    """
    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    prefix = f"posthog-events-{str(uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
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
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": None,
            "_timestamp": "2023-04-25 13:30:00",
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
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": None,
            "_timestamp": "2023-04-25 14:29:00",
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
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(s3_client, bucket_name, prefix, events, compression)


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"])
async def test_s3_export_workflow_with_minio_bucket_and_custom_key_prefix(
    client: HttpClient, s3_client, bucket_name, compression
):
    """Test the S3BatchExport Workflow utilizing a custom key prefix.

    We will be asserting that exported events land in the appropiate S3 key according to the prefix.
    """
    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    prefix = "posthog-{table}/{year}-{month}-{day}/{hour}:{minute}:{second}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
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
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": "2023-04-25 13:31:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
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
                    execution_timeout=dt.timedelta(seconds=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    expected_key_prefix = prefix.format(
        table="events", year="2023", month="04", day="25", hour="14", minute="30", second="00"
    )
    objects = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=expected_key_prefix)
    key = objects["Contents"][0].get("Key")
    assert len(objects.get("Contents", [])) == 1
    assert key.startswith(expected_key_prefix)

    assert_events_in_s3(s3_client, bucket_name, expected_key_prefix, events, compression)


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"])
async def test_s3_export_workflow_with_minio_bucket_produces_no_duplicates(
    client: HttpClient, s3_client, bucket_name, compression
):
    """Test that S3 Export Workflow end-to-end by using a local MinIO bucket instead of S3.

    In this particular instance of the test, we assert no duplicates are exported to S3.
    """
    ch_client = ClickHouseClient(
        url=settings.CLICKHOUSE_HTTP_URL,
        user=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DATABASE,
    )

    prefix = f"posthog-events-{str(uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
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

    duplicate_id = str(uuid4())
    duplicate_distinct_id = str(uuid4())
    duplicate_person_id = str(uuid4())
    events: list[EventValues] = [
        {
            "uuid": str(uuid4()),
            "event": "test",
            "timestamp": "2023-04-25 13:30:00.000000",
            "created_at": "2023-04-25 13:30:00.000000",
            "inserted_at": f"2023-04-25 13:30:00.000000",
            "_timestamp": "2023-04-25 13:30:00",
            "person_id": str(uuid4()),
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": str(uuid4()),
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
        {
            "uuid": duplicate_id,
            "event": "test",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": f"2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": duplicate_person_id,
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": duplicate_distinct_id,
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        },
    ]
    events_with_duplicates = events + [
        {
            "uuid": duplicate_id,
            "event": "test",
            "timestamp": "2023-04-25 14:29:00.000000",
            "created_at": "2023-04-25 14:29:00.000000",
            "inserted_at": f"2023-04-25 14:29:00.000000",
            "_timestamp": "2023-04-25 14:29:00",
            "person_id": duplicate_person_id,
            "person_properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "team_id": team.pk,
            "properties": {"$browser": "Chrome", "$os": "Mac OS X"},
            "distinct_id": duplicate_distinct_id,
            "elements_chain": "this is a comman, separated, list, of css selectors(?)",
        }
    ]

    # Insert some data into the `sharded_events` table.
    await insert_events(
        client=ch_client,
        events=events_with_duplicates,
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

    assert_events_in_s3(s3_client, bucket_name, prefix, events, compression)


@pytest_asyncio.fixture
async def organization():
    organization = await acreate_organization("test")
    yield organization
    await sync_to_async(organization.delete)()  # type: ignore


@pytest_asyncio.fixture
async def team(organization):
    team = await acreate_team(organization=organization)
    yield team
    await sync_to_async(team.delete)()  # type: ignore


@pytest_asyncio.fixture
async def batch_export(team):
    prefix = f"posthog-events-{str(uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": "test-bucket",
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": "gzip",
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": "hour",
    }

    batch_export = await acreate_batch_export(
        team_id=team.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    client = await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        settings.TEMPORAL_CLIENT_ROOT_CA,
        settings.TEMPORAL_CLIENT_CERT,
        settings.TEMPORAL_CLIENT_KEY,
    )
    await adelete_batch_export(batch_export, client)


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_handles_insert_activity_errors(team, batch_export):
    """Test that S3 Export Workflow can gracefully handle errors when inserting S3 data."""
    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **batch_export.destination.config,
    )

    @activity.defn(name="insert_into_s3_activity")
    async def insert_into_s3_activity_mocked(_: S3InsertInputs) -> str:
        raise ValueError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[create_export_run, insert_into_s3_activity_mocked, update_export_run_status],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
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
        assert run.status == "Failed"
        assert run.latest_error == "ValueError: A useful error message"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_handles_cancellation(team, batch_export):
    """Test that S3 Export Workflow can gracefully handle cancellations when inserting S3 data."""
    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=team.pk,
        batch_export_id=str(batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **batch_export.destination.config,
    )

    @activity.defn(name="insert_into_s3_activity")
    async def never_finish_activity(_: S3InsertInputs) -> str:
        while True:
            activity.heartbeat()
            await asyncio.sleep(1)

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[create_export_run, never_finish_activity, update_export_run_status],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await asyncio.sleep(5)
            await handle.cancel()

            with pytest.raises(WorkflowFailureError):
                await handle.result()

        runs = await afetch_batch_export_runs(batch_export_id=batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Cancelled"
        assert run.latest_error == "Cancelled"


# We don't care about these for the next test, just need something to be defined.
base_inputs = {
    "bucket_name": "test",
    "region": "test",
    "team_id": 1,
}


@pytest.mark.parametrize(
    "inputs,expected",
    [
        (
            S3InsertInputs(
                prefix="/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
    ],
)
def test_get_s3_key(inputs, expected):
    """Test the get_s3_key function renders the expected S3 key given inputs."""
    result = get_s3_key(inputs)
    assert result == expected
