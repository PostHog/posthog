import asyncio
import collections
import datetime as dt
import functools
import gzip
import itertools
import json
import os
import uuid
from unittest import mock

import boto3
import botocore.exceptions
import brotli
import pytest
import pytest_asyncio
from asgiref.sync import sync_to_async
from django.conf import settings
from django.test import override_settings
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.tests.batch_exports.base import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
    amaterialize,
    insert_events,
    to_isoformat,
)
from posthog.temporal.workflows.base import create_export_run, update_export_run_status
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
    return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


S3BatchExportTestParameters = collections.namedtuple(
    "S3BatchExportTestParameters", ("interval", "compression", "encryption", "exclude_events")
)

ALL_S3_TEST_PARAMETERS = [
    S3BatchExportTestParameters(
        interval=interval, compression=compression, encryption=encryption, exclude_events=exclude_events
    )
    for (interval, compression, encryption, exclude_events) in itertools.product(
        ["hour", "day"], [None, "gzip", "brotli"], [None, "AES256", "aws:kms"], [None, ["test-1", "test-2"]]
    )
]


@pytest_asyncio.fixture(params=ALL_S3_TEST_PARAMETERS)
async def s3_batch_export(request, ateam, temporal_client, bucket_name):
    batch_export_test_params = request.param
    prefix = f"posthog-events-{str(uuid.uuid4())}"
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": batch_export_test_params.compression,
            "encryption": batch_export_test_params.encryption,
            "exclude_events": batch_export_test_params.exclude_events,
            "kms_key_id": os.getenv("S3_TEST_KMS_KEY_ID", None),
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-export",
        "destination": destination_data,
        "interval": batch_export_test_params.interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


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

    json_data.sort(key=lambda x: x["event"])

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
    expected_events.sort(key=lambda x: x["event"])

    # First check one event, the first one, so that we can get a nice diff if
    # the included data is different.
    assert json_data[0] == expected_events[0]
    assert len(json_data) == len(expected_events)
    for event_1, event_2 in zip(json_data, expected_events):
        assert event_1 == event_2


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
@pytest.mark.parametrize(
    "compression,exclude_events",
    itertools.product([None, "gzip", "brotli"], [None, ["test-1", "test-2"]]),
)
async def test_insert_into_s3_activity_puts_data_into_s3(
    bucket_name, s3_client, activity_environment, compression, exclude_events, ch_client, ateam
):
    """Test that the insert_into_s3_activity function puts data into S3."""
    data_interval_start = "2023-04-20 14:00:00"
    data_interval_end = "2023-04-21 15:00:00"

    events, _, _ = await insert_events(
        client=ch_client,
        team=ateam,
        start_time=dt.datetime.fromisoformat(data_interval_start),
        end_time=dt.datetime.fromisoformat(data_interval_end),
        n=1000,
    )
    # Add a materialized column such that we can verify that it is NOT included
    # in the export.
    await amaterialize("events", "$browser")

    # Make a random string to prefix the S3 keys with. This allows us to ensure
    # isolation of the test, and also to check that the data is being written.
    prefix = str(uuid.uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
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
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_with_minio_bucket(s3_client, s3_batch_export, ch_client):
    """Test S3 Export Workflow end-to-end by using a local MinIO bucket instead of S3.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.
    """
    if s3_batch_export.destination.config.get("encryption", None) is not None:
        pytest.skip("Encryption is not supported in MinIO")

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        s3_batch_export.destination.config["prefix"],
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.skipif(
    "S3_TEST_BUCKET" not in os.environ or not check_valid_credentials(),
    reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
)
@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_with_s3_bucket(s3_batch_export, ch_client):
    """Test S3 Export Workflow end-to-end by using an S3 bucket.

    The S3_TEST_BUCKET environment variable is used to set the name of the bucket for this test.
    This test will be skipped if no valid AWS credentials exist, or if the S3_TEST_BUCKET environment
    variable is not set.

    The workflow should update the batch export run status to completed and produce the expected
    records to the S3 bucket.
    """
    s3_batch_export.destination.config["bucket_name"] = os.environ["S3_TEST_BUCKET"]
    # Update to use real bucket
    await sync_to_async(s3_batch_export.save)()  # type: ignore

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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
                    execution_timeout=dt.timedelta(seconds=20),
                )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        s3_batch_export.destination.config["prefix"],
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_with_minio_bucket_and_a_lot_of_data(s3_client, s3_batch_export, ch_client):
    """Test the full S3 workflow targetting a MinIO bucket.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.
    """
    if s3_batch_export.destination.config.get("encryption", None) is not None:
        pytest.skip("Encryption is not supported in MinIO")
    if s3_batch_export.destination.config.get("compression", "") == "brotli":
        pytest.skip("Brotli performs badly with a lot of data")

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
        n=1000000,
    )

    prefix = f"posthog-events-{str(uuid.uuid4())}-{{year}}-{{month}}-{{day}}"
    s3_batch_export.destination.config["prefix"] = prefix
    # Update to use new prefix
    await sync_to_async(s3_batch_export.save)()  # type: ignore

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    parametrized_prefix = prefix.format(
        table="events",
        year=end_time.year,
        month=end_time.strftime("%m"),
        day=end_time.strftime("%d"),
    )

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        parametrized_prefix,
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_defaults_to_timestamp_on_null_inserted_at(s3_client, s3_batch_export, ch_client):
    """Test the full S3 workflow targetting a MinIO bucket.

    In this scenario we assert that when inserted_at is NULL, we default to _timestamp.
    This scenario is relevant for rows inserted before the migration happened.
    """
    if s3_batch_export.destination.config.get("encryption", None) is not None:
        pytest.skip("Encryption is not supported in MinIO")

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
        override_values={"inserted_at": None},
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        s3_batch_export.destination.config["prefix"],
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_with_minio_bucket_and_custom_key_prefix(s3_client, s3_batch_export, ch_client):
    """Test the S3BatchExport Workflow utilizing a custom key prefix.

    We will be asserting that exported events land in the appropiate S3 key according to the prefix.
    """
    if s3_batch_export.destination.config.get("encryption", None) is not None:
        pytest.skip("Encryption is not supported in MinIO")

    prefix = "posthog-{table}/{year}-{month}-{day}/{hour}:{minute}:{second}"
    s3_batch_export.destination.config["prefix"] = prefix
    # Update to use new prefix
    await sync_to_async(s3_batch_export.save)()  # type: ignore

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    parametrized_prefix = prefix.format(
        table="events",
        year=end_time.year,
        month=end_time.strftime("%m"),
        day=end_time.strftime("%d"),
        hour=end_time.strftime("%H"),
        minute=end_time.strftime("%M"),
        second=end_time.strftime("%S"),
    )

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        parametrized_prefix,
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
@pytest.mark.usefixtures("truncate_events")
async def test_s3_export_workflow_with_minio_bucket_produces_no_duplicates(s3_client, s3_batch_export, ch_client):
    """Test that S3 Export Workflow end-to-end by using a local MinIO bucket instead of S3.

    In this particular instance of the test, we assert no duplicates are exported to S3.
    """
    if s3_batch_export.destination.config.get("encryption", None) is not None:
        pytest.skip("Encryption is not supported in MinIO")

    if s3_batch_export.interval == "hour":
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 20, 1, 0, 0)
    else:
        start_time, end_time = dt.datetime(2023, 9, 20, 0, 0, 0), dt.datetime(2023, 9, 21, 0, 0, 0)

    events, _, _ = await insert_events(
        client=ch_client,
        team=s3_batch_export.team,
        start_time=start_time,
        end_time=end_time,
        duplicate=True,
    )

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=s3_batch_export.team.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=end_time.isoformat(),
        interval=s3_batch_export.interval,
        **s3_batch_export.destination.config,
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

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    assert_events_in_s3(
        s3_client,
        s3_batch_export.destination.config["bucket_name"],
        s3_batch_export.destination.config["prefix"],
        events,
        s3_batch_export.destination.config["compression"],
        s3_batch_export.destination.config["exclude_events"],
    )


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_handles_insert_activity_errors(ateam, s3_batch_export):
    """Test that S3 Export Workflow can gracefully handle errors when inserting S3 data."""
    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **s3_batch_export.destination.config,
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

        runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
        assert len(runs) == 1

        run = runs[0]
        assert run.status == "Failed"
        assert run.latest_error == "ValueError: A useful error message"


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_s3_export_workflow_handles_cancellation(ateam, s3_batch_export):
    """Test that S3 Export Workflow can gracefully handle cancellations when inserting S3 data."""
    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end="2023-04-25 14:30:00.000000",
        **s3_batch_export.destination.config,
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

        runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
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
