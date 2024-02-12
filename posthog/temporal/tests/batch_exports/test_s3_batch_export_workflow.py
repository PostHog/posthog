import asyncio
import contextlib
import datetime as dt
import functools
import gzip
import json
import os
from random import randint
from unittest import mock
from uuid import uuid4

import aioboto3
import botocore.exceptions
import brotli
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.batch_exports.service import BatchExportSchema
from posthog.temporal.batch_exports.batch_exports import (
    create_export_run,
    iter_records,
    update_export_run_status,
)
from posthog.temporal.batch_exports.clickhouse import ClickHouseClient
from posthog.temporal.batch_exports.s3_batch_export import (
    HeartbeatDetails,
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3InsertInputs,
    get_s3_key,
    insert_into_s3_activity,
    s3_default_fields,
)
from posthog.temporal.tests.utils.events import (
    generate_test_events_in_clickhouse,
)
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_ROOT_BUCKET = "test-batch-exports"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


async def check_valid_credentials() -> bool:
    """Check if there are valid AWS credentials in the environment."""
    session = aioboto3.Session()
    sts = await session.client("sts")
    try:
        await sts.get_caller_identity()
    except botocore.exceptions.ClientError:
        return False
    else:
        return True


@pytest.fixture
def compression(request) -> str | None:
    """A parametrizable fixture to configure compression.

    By decorating a test function with @pytest.mark.parametrize("compression", ..., indirect=True)
    it's possible to set the compression that will be used to create an S3
    BatchExport. Possible values are "brotli", "gzip", or None.
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def encryption(request) -> str | None:
    """A parametrizable fixture to configure a batch export encryption.

    By decorating a test function with @pytest.mark.parametrize("encryption", ..., indirect=True)
    it's possible to set the exclude_events that will be used to create an S3
    BatchExport. Any list of event names can be used, or None.
    """
    try:
        return request.param
    except AttributeError:
        return None


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid4())}"


@pytest.fixture
def s3_key_prefix():
    """An S3 key prefix to use when putting files in a bucket."""
    return f"posthog-events-{str(uuid4())}"


async def delete_all_from_s3(minio_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    """Manage an S3 client to interact with a MinIO bucket.

    Yields the client after creating a bucket. Upon resuming, we delete
    the contents and the bucket itself.
    """
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

        await minio_client.delete_bucket(Bucket=bucket_name)


async def assert_clickhouse_records_in_s3(
    s3_compatible_client,
    clickhouse_client: ClickHouseClient,
    bucket_name: str,
    key_prefix: str,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    compression: str | None = None,
):
    """Assert ClickHouse records are written to JSON in key_prefix in S3 bucket_name.

    Arguments:
        s3_compatible_client: An S3 client used to read records; can be MinIO if doing local testing.
        clickhouse_client: A ClickHouseClient used to read records that are expected to be exported.
        team_id: The ID of the team that we are testing for.
        bucket_name: S3 bucket name where records are exported to.
        key_prefix: S3 key prefix where records are exported to.
        data_interval_start: Start of the batch period for exported records.
        data_interval_end: End of the batch period for exported records.
        exclude_events: Event names to be excluded from the export.
        include_events: Event names to be included in the export.
        batch_export_schema: Custom schema used in the batch export.
        compression: Optional compression used in upload.
    """
    # List the objects in the bucket with the prefix.
    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    # Check that there is only one object.
    assert len(objects.get("Contents", [])) == 1

    # Get the object.
    key = objects["Contents"][0].get("Key")
    assert key
    s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
    data = await s3_object["Body"].read()

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

    if batch_export_schema is not None:
        schema_column_names = [field["alias"] for field in batch_export_schema["fields"]]
    else:
        schema_column_names = [field["alias"] for field in s3_default_fields()]

    json_columns = ("properties", "person_properties", "set", "set_once")

    expected_records = []
    for record_batch in iter_records(
        client=clickhouse_client,
        team_id=team_id,
        interval_start=data_interval_start.isoformat(),
        interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        fields=batch_export_schema["fields"] if batch_export_schema is not None else s3_default_fields(),
        extra_query_parameters=batch_export_schema["values"] if batch_export_schema is not None else None,
    ):
        for record in record_batch.to_pylist():
            expected_record = {}
            for k, v in record.items():
                if k not in schema_column_names or k == "_inserted_at":
                    # _inserted_at is not exported, only used for tracking progress.
                    continue

                if k in json_columns and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    # Some type precision is lost when json dumping to S3, so we have to cast this to str to match.
                    expected_record[k] = v.isoformat()
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    assert len(json_data) == len(expected_records)
    assert json_data[0] == expected_records[0]
    assert json_data == expected_records


TEST_S3_SCHEMAS: list[BatchExportSchema | None] = [
    {
        "fields": [
            {"expression": "event", "alias": "my_event_name"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    {
        "fields": [
            {"expression": "event", "alias": "my_event_name"},
            {"expression": "inserted_at", "alias": "inserted_at"},
            {"expression": "1 + 1", "alias": "two"},
        ],
        "values": {},
    },
    None,
]


@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("batch_export_schema", TEST_S3_SCHEMAS)
async def test_insert_into_s3_activity_puts_data_into_s3(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    exclude_events,
    batch_export_schema: BatchExportSchema | None,
):
    """Test that the insert_into_s3_activity function ends up with data into S3.

    We use the generate_test_events_in_clickhouse function to generate several sets
    of events. Some of these sets are expected to be exported, and others not. Expected
    events are those that:
    * Are created for the team_id of the batch export.
    * Are created in the date range of the batch export.
    * Are not duplicates of other events that are in the same batch.
    * Do not have an event name contained in the batch export's exclude_events.

    Once we have these events, we pass them to the assert_clickhouse_records_in_s3 function to check
    that they appear in the expected S3 bucket and key.
    """
    data_interval_start = dt.datetime(2023, 4, 20, 14, 0, 0, tzinfo=dt.timezone.utc)
    data_interval_end = dt.datetime(2023, 4, 25, 15, 0, 0, tzinfo=dt.timezone.utc)

    # Generate a random team id integer. There's still a chance of a collision,
    # but it's very small.
    team_id = randint(1, 1000000)

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10000,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=team_id,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=5,
        count_outside_range=0,
        count_other_team=0,
        properties=None,
        person_properties=None,
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=team_id,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    # Make a random string to prefix the S3 keys with. This allows us to ensure
    # isolation of the test, and also to check that the data is being written.
    prefix = str(uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=team_id,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        compression=compression,
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        with mock.patch(
            "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
            side_effect=create_test_client,
        ):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=prefix,
        team_id=team_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
    )


@pytest_asyncio.fixture
async def s3_batch_export(
    ateam, s3_key_prefix, bucket_name, compression, interval, exclude_events, temporal_client, encryption
):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": s3_key_prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "compression": compression,
            "exclude_events": exclude_events,
            "encryption": encryption,
            "kms_key_id": os.getenv("S3_TEST_KMS_KEY_ID") if encryption == "aws:kms" else None,
        },
    }

    batch_export_data = {
        "name": "my-production-s3-bucket-destination",
        "destination": destination_data,
        "interval": interval,
    }

    batch_export = await acreate_batch_export(
        team_id=ateam.pk,
        name=batch_export_data["name"],
        destination_data=batch_export_data["destination"],
        interval=batch_export_data["interval"],
    )

    yield batch_export

    await adelete_batch_export(batch_export, temporal_client)


@pytest.mark.parametrize("interval", ["hour", "day"], indirect=True)
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("batch_export_schema", TEST_S3_SCHEMAS)
async def test_s3_export_workflow_with_minio_bucket(
    clickhouse_client,
    minio_client,
    ateam,
    s3_batch_export,
    bucket_name,
    interval,
    compression,
    exclude_events,
    s3_key_prefix,
    batch_export_schema,
):
    """Test S3BatchExport Workflow end-to-end by using a local MinIO bucket instead of S3.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.

    We use a BatchExport model to provide accurate inputs to the Workflow and because the Workflow
    will require its prescense in the database when running. This model is indirectly parametrized
    by several fixtures. Refer to them for more information.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_s3_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            # We patch the S3 client to return our client that targets MinIO.
            with mock.patch(
                "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
                side_effect=create_test_client,
            ):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    execution_timeout=dt.timedelta(minutes=10),
                )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
        compression=compression,
    )


@pytest_asyncio.fixture
async def s3_client(bucket_name, s3_key_prefix):
    """Manage an S3 client to interact with an S3 bucket.

    Yields the client after assuming the test bucket exists. Upon resuming, we delete
    the contents of the bucket under the key prefix we are testing. This opens up the door
    to bugs that could delete all other data in your bucket. I *strongly* recommend
    using a disposable bucket to run these tests or sticking to other tests that use the
    local development MinIO.
    """
    async with aioboto3.Session().client("s3") as minio_client:
        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix=s3_key_prefix)


@pytest.mark.skipif(
    "S3_TEST_BUCKET" not in os.environ or not check_valid_credentials(),
    reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
)
@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("encryption", [None, "AES256", "aws:kms"], indirect=True)
@pytest.mark.parametrize("bucket_name", [os.getenv("S3_TEST_BUCKET")], indirect=True)
@pytest.mark.parametrize("batch_export_schema", TEST_S3_SCHEMAS)
async def test_s3_export_workflow_with_s3_bucket(
    s3_client,
    clickhouse_client,
    interval,
    s3_batch_export,
    bucket_name,
    compression,
    s3_key_prefix,
    encryption,
    exclude_events,
    ateam,
    batch_export_schema,
):
    """Test S3 Export Workflow end-to-end by using an S3 bucket.

    The S3_TEST_BUCKET environment variable is used to set the name of the bucket for this test.
    This test will be skipped if no valid AWS credentials exist, or if the S3_TEST_BUCKET environment
    variable is not set.

    The workflow should update the batch export run status to completed and produce the expected
    records to the S3 bucket.

    We use a BatchExport model to provide accurate inputs to the Workflow and because the Workflow
    will require its prescense in the database when running. This model is indirectly parametrized
    by several fixtures. Refer to them for more information.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    if exclude_events:
        for event_name in exclude_events:
            await generate_test_events_in_clickhouse(
                client=clickhouse_client,
                team_id=ateam.pk,
                start_time=data_interval_start,
                end_time=data_interval_end,
                count=5,
                count_outside_range=0,
                count_other_team=0,
                event_name=event_name,
            )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        **s3_batch_export.destination.config,
    )

    @contextlib.asynccontextmanager
    async def create_minio_client(*args, **kwargs):
        """Mock function to return an already initialized S3 client."""
        yield s3_client

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_s3_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
                side_effect=create_minio_client,
            ):
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

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_schema=batch_export_schema,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
    )


async def test_s3_export_workflow_with_minio_bucket_and_a_lot_of_data(
    clickhouse_client,
    minio_client,
    bucket_name,
    ateam,
    compression,
    exclude_events,
    s3_key_prefix,
    interval,
    s3_batch_export,
):
    """Test the S3BatchExport Workflow end-to-end by using a local MinIO bucket instead of S3.

    This test is the same as test_s3_export_workflow_with_minio_bucket, but we significantly increase the number
    of rows generated to export to provide some guidance on whether we can perform under load.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100000,
        count_outside_range=1000,
        count_other_team=1000,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_s3_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
                side_effect=create_test_client,
            ):
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

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        compression=compression,
    )


async def test_s3_export_workflow_defaults_to_timestamp_on_null_inserted_at(
    clickhouse_client, minio_client, bucket_name, compression, interval, s3_batch_export, s3_key_prefix, ateam
):
    """Test the S3BatchExport Workflow end-to-end by using a local MinIO bucket instead of S3.

    This test is the same as test_s3_export_workflow_with_minio_bucket, but we create events with None as
    inserted_at to assert we properly default to _timestamp. This is relevant for rows inserted before inserted_at
    was added.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
        inserted_at=None,
    )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_s3_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
                side_effect=create_test_client,
            ):
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

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        compression=compression,
    )


@pytest.mark.parametrize(
    "s3_key_prefix",
    [
        "posthog-{table}/{year}-{month}-{day}/{hour}:{minute}:{second}",
        "posthog-{table}/{hour}:{minute}:{second}/{year}-{month}-{day}",
        "posthog-{table}/{hour}:{minute}:{second}",
        "posthog/{year}-{month}-{day}/{hour}:{minute}:{second}",
        "{year}-{month}-{day}",
    ],
    indirect=True,
)
async def test_s3_export_workflow_with_minio_bucket_and_custom_key_prefix(
    clickhouse_client, ateam, minio_client, bucket_name, compression, interval, s3_batch_export, s3_key_prefix
):
    """Test the S3BatchExport Workflow end-to-end by specifying a custom key prefix.

    This test is the same as test_s3_export_workflow_with_minio_bucket, but we create events with None as
    inserted_at to assert we properly default to _timestamp. This is relevant for rows inserted before inserted_at
    was added.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100,
        count_outside_range=10,
        count_other_team=10,
        duplicate=True,
        properties={"$browser": "Chrome", "$os": "Mac OS X"},
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                create_export_run,
                insert_into_s3_activity,
                update_export_run_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with mock.patch(
                "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
                side_effect=create_test_client,
            ):
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

    expected_key_prefix = s3_key_prefix.format(
        table="events",
        year=data_interval_end.year,
        # All of these must include leading 0s.
        month=data_interval_end.strftime("%m"),
        day=data_interval_end.strftime("%d"),
        hour=data_interval_end.strftime("%H"),
        minute=data_interval_end.strftime("%M"),
        second=data_interval_end.strftime("%S"),
    )
    objects = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=expected_key_prefix)
    key = objects["Contents"][0].get("Key")
    assert len(objects.get("Contents", [])) == 1
    assert key.startswith(expected_key_prefix)

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        compression=compression,
    )


async def test_s3_export_workflow_handles_insert_activity_errors(ateam, s3_batch_export, interval):
    """Test S3BatchExport Workflow can handle errors from executing the insert into S3 activity.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
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
            activities=[
                create_export_run,
                insert_into_s3_activity_mocked,
                update_export_run_status,
            ],
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


@pytest.mark.asyncio
async def test_s3_export_workflow_handles_cancellation(ateam, s3_batch_export, interval):
    """Test that S3 Export Workflow can gracefully handle cancellations when inserting S3 data.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
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
            activities=[
                create_export_run,
                never_finish_activity,
                update_export_run_status,
            ],
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
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
        (
            S3InsertInputs(
                prefix="my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/my-fancy-prefix-with-a-forwardslash/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "my-fancy-prefix-with-a-forwardslash/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.gz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.jsonl.br",
        ),
    ],
)
def test_get_s3_key(inputs, expected):
    """Test the get_s3_key function renders the expected S3 key given inputs."""
    result = get_s3_key(inputs)
    assert result == expected


async def test_insert_into_s3_activity_heartbeats(
    clickhouse_client, ateam, bucket_name, s3_batch_export, minio_client, activity_environment, s3_key_prefix
):
    """Test that the insert_into_s3_activity activity sends heartbeats.

    We use a function that runs on_heartbeat to check and track the heartbeat contents.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-20T14:30:00.000000+00:00")
    data_interval_start = data_interval_end - s3_batch_export.interval_time_delta

    n_expected_parts = 3

    for i in range(1, n_expected_parts + 1):
        part_inserted_at = data_interval_end - s3_batch_export.interval_time_delta / i

        await generate_test_events_in_clickhouse(
            client=clickhouse_client,
            team_id=ateam.pk,
            start_time=data_interval_start,
            end_time=data_interval_end,
            count=1,
            count_outside_range=0,
            count_other_team=0,
            duplicate=False,
            # We need at least 5MB for a multi-part upload which is what we are testing.
            properties={"$chonky": ("a" * 5 * 1024**2)},
            inserted_at=part_inserted_at,
        )

    current_part_number = 1

    def assert_heartbeat_details(*details):
        """A function to track and assert we are heartbeating."""
        nonlocal current_part_number

        details = HeartbeatDetails.from_activity_details(details)

        last_uploaded_part_dt = dt.datetime.fromisoformat(details.last_uploaded_part_timestamp)
        assert last_uploaded_part_dt == data_interval_end - s3_batch_export.interval_time_delta / current_part_number

        assert len(details.upload_state.parts) == current_part_number
        current_part_number = len(details.upload_state.parts) + 1

    activity_environment.on_heartbeat = assert_heartbeat_details

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    )

    with override_settings(BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
        with mock.patch(
            "posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session.client",
            side_effect=create_test_client,
        ):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    # This checks that the assert_heartbeat_details function was actually called.
    # The '+ 1' is because we increment current_part_number one last time after we are done.
    assert current_part_number == n_expected_parts + 1

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )
