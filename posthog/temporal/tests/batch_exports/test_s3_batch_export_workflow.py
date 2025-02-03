import asyncio
import contextlib
import datetime as dt
import functools
import io
import json
import os
import re
import uuid
from dataclasses import asdict
from unittest import mock
from unittest.mock import patch

import aioboto3
import botocore.exceptions
import pyarrow as pa
import pytest
import pytest_asyncio
from django.conf import settings
from django.test import override_settings
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog import constants
from posthog.batch_exports.service import (
    BackfillDetails,
    BatchExportModel,
    BatchExportSchema,
)
from posthog.temporal.batch_exports.batch_exports import (
    finish_batch_export_run,
    start_batch_export_run,
)
from posthog.temporal.batch_exports.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    IntermittentUploadPartTimeoutError,
    InvalidS3EndpointError,
    S3BatchExportInputs,
    S3BatchExportWorkflow,
    S3HeartbeatDetails,
    S3InsertInputs,
    S3MultiPartUpload,
    get_s3_key,
    insert_into_s3_activity,
    s3_default_fields,
)
from posthog.temporal.batch_exports.spmc import Producer, RecordBatchQueue
from posthog.temporal.batch_exports.temporary_file import UnsupportedFileFormatError
from posthog.temporal.common.clickhouse import ClickHouseClient
from posthog.temporal.tests.batch_exports.utils import mocked_start_batch_export_run
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse
from posthog.temporal.tests.utils.models import (
    acreate_batch_export,
    adelete_batch_export,
    afetch_batch_export_runs,
)
from posthog.temporal.tests.utils.s3 import read_parquet_from_s3, read_s3_data_as_json

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_DATA_INTERVAL_END = dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
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
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


@pytest.fixture
def s3_key_prefix(request):
    """An S3 key prefix to use when putting files in a bucket."""
    try:
        return request.param
    except AttributeError:
        return f"posthog-data-{str(uuid.uuid4())}"


@pytest.fixture
def file_format(request) -> str:
    """S3 file format."""
    try:
        return request.param
    except AttributeError:
        return f"JSONLines"


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


async def assert_files_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert that there are files in S3 under key_prefix and return the combined contents, and the keys of files found."""
    expected_file_extension = FILE_FORMAT_EXTENSIONS[file_format]
    if compression is not None:
        expected_file_extension = f"{expected_file_extension}.{COMPRESSION_EXTENSIONS[compression]}"

    objects = await s3_compatible_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    s3_data = []
    keys = []
    assert objects.get("KeyCount", 0) > 0
    assert "Contents" in objects
    for obj in objects["Contents"]:
        key = obj.get("Key")
        if not key.endswith(expected_file_extension):
            continue

        keys.append(key)

        if file_format == "Parquet":
            s3_data.extend(await read_parquet_from_s3(bucket_name, key, json_columns))

        elif file_format == "JSONLines":
            s3_object = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
            data = await s3_object["Body"].read()
            s3_data.extend(read_s3_data_as_json(data, compression))
        else:
            raise ValueError(f"Unsupported file format: {file_format}")

    return s3_data, keys


async def assert_file_in_s3(s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns):
    """Assert a file is in S3 and return its contents."""
    s3_data, keys = await assert_files_in_s3(
        s3_compatible_client, bucket_name, key_prefix, file_format, compression, json_columns
    )
    assert len(keys) == 1
    return s3_data


async def read_json_file_from_s3(s3_compatible_client, bucket_name, key) -> list | dict:
    s3_object: dict = await s3_compatible_client.get_object(Bucket=bucket_name, Key=key)
    data = await s3_object["Body"].read()
    data = read_s3_data_as_json(data, None)
    return data[0]


async def get_record_batch_from_queue(queue, produce_task):
    while not queue.empty() or not produce_task.done():
        try:
            record_batch = queue.get_nowait()
        except asyncio.QueueEmpty:
            if produce_task.done():
                break
            else:
                await asyncio.sleep(0.1)
                continue

        return record_batch
    return None


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
    batch_export_model: BatchExportModel | BatchExportSchema | None = None,
    compression: str | None = None,
    file_format: str = "JSONLines",
    backfill_details: BackfillDetails | None = None,
    allow_duplicates: bool = False,
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
    json_columns = ("properties", "person_properties", "set", "set_once")
    s3_data = await assert_file_in_s3(
        s3_compatible_client=s3_compatible_client,
        bucket_name=bucket_name,
        key_prefix=key_prefix,
        file_format=file_format,
        compression=compression,
        json_columns=json_columns,
    )

    schema_column_names = [field["alias"] for field in s3_default_fields()]
    if batch_export_model is not None:
        if isinstance(batch_export_model, BatchExportModel):
            model_name = batch_export_model.name
            fields = batch_export_model.schema["fields"] if batch_export_model.schema is not None else None
            filters = batch_export_model.filters
            extra_query_parameters = (
                batch_export_model.schema["values"] if batch_export_model.schema is not None else None
            )
        else:
            model_name = "custom"
            fields = batch_export_model["fields"]
            filters = None
            extra_query_parameters = batch_export_model["values"]
    else:
        model_name = "events"
        extra_query_parameters = None
        fields = None
        filters = None

    if fields is not None:
        schema_column_names = [field["alias"] for field in fields]
    elif isinstance(batch_export_model, BatchExportModel) and batch_export_model.name == "persons":
        schema_column_names = [
            "team_id",
            "distinct_id",
            "person_id",
            "properties",
            "person_version",
            "person_distinct_id_version",
            "_inserted_at",
            "created_at",
        ]

    expected_records = []

    queue = RecordBatchQueue()
    producer = Producer()
    producer_task = await producer.start(
        queue=queue,
        model_name=model_name,
        is_backfill=is_backfill,
        team_id=team_id,
        full_range=(data_interval_start, data_interval_end),
        done_ranges=[],
        fields=fields,
        filters=filters,
        destination_default_fields=s3_default_fields(),
        exclude_events=exclude_events,
        include_events=include_events,
        destination_default_fields=s3_default_fields(),
        backfill_details=backfill_details,
        use_latest_schema=True,
    )
    while not queue.empty() or not producer_task.done():
        record_batch = await get_record_batch_from_queue(queue, producer_task)
        if record_batch is None:
            break

        for record in record_batch.to_pylist():
            expected_record = {}
            for k, v in record.items():
                if k in json_columns and v is not None:
                    expected_record[k] = json.loads(v)
                elif isinstance(v, dt.datetime):
                    # Some type precision is lost when json dumping to S3, so we have to cast this to str to match.
                    expected_record[k] = v.isoformat()
                else:
                    expected_record[k] = v

            expected_records.append(expected_record)

    if "team_id" in schema_column_names:
        assert all(record["team_id"] == team_id for record in s3_data)

    assert s3_data[0] == expected_records[0]
    if allow_duplicates:
        # de-duplicate based on uuid
        s3_data = list({record["uuid"]: record for record in s3_data}.values())
    assert len(s3_data) == len(expected_records)
    assert s3_data == expected_records


TEST_S3_MODELS: list[BatchExportModel | BatchExportSchema | None] = [
    BatchExportModel(
        name="a-custom-model",
        schema={
            "fields": [
                {"expression": "event", "alias": "my_event_name"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
                {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
                {"expression": "nullIf(properties, '')", "alias": "all_properties"},
            ],
            "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
        },
    ),
    BatchExportModel(name="events", schema=None),
    BatchExportModel(
        name="events",
        schema=None,
        filters=[
            {"key": "$browser", "operator": "exact", "type": "event", "value": ["Chrome"]},
            {"key": "$os", "operator": "exact", "type": "event", "value": ["Mac OS X"]},
        ],
    ),
    BatchExportModel(name="persons", schema=None),
    BatchExportModel(name="sessions", schema=None),
    {
        "fields": [
            {"expression": "event", "alias": "my_event_name"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_0)s), '')", "alias": "browser"},
            {"expression": "nullIf(JSONExtractString(properties, %(hogql_val_1)s), '')", "alias": "os"},
            {"expression": "nullIf(properties, '')", "alias": "all_properties"},
        ],
        "values": {"hogql_val_0": "$browser", "hogql_val_1": "$os"},
    },
    None,
]


@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys())
async def test_insert_into_s3_activity_puts_data_into_s3(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    ateam,
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
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

    prefix = str(uuid.uuid4())

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        records_exported = await activity_environment.run(insert_into_s3_activity, insert_inputs)

    events_to_export_created, persons_to_export_created = generate_test_data
    assert (
        records_exported == len(events_to_export_created)
        or records_exported == len(persons_to_export_created)
        or records_exported == len([event for event in events_to_export_created if event["properties"] is not None])
    )

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
        file_format=file_format,
        backfill_details=None,
    )


@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys())
# Use 0 to test that the file is not split up and 6MB since this is slightly
# larger than the default 5MB chunk size for multipart uploads.
@pytest.mark.parametrize("max_file_size_mb", [None, 6])
async def test_insert_into_s3_activity_puts_splitted_files_into_s3(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    max_file_size_mb,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel,
    ateam,
):
    """Test that the insert_into_s3_activity function splits up large files into
    multiple parts based on the max file size configuration.

    If max file size is set to 0 then the file should not be split up.

    This test needs to generate a lot of data to ensure that the file is large enough to be split up.
    """

    if file_format == "JSONLines" and compression is not None:
        pytest.skip("Compressing large JSONLines files takes too long to run; skipping for now")

    prefix = str(uuid.uuid4())

    events_1, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$prop1": 123},
    )

    events_2, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$prop1": 123},
    )

    events_to_export_created = events_1 + events_2

    heartbeat_details: list[S3HeartbeatDetails] = []

    def track_hearbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details

        s3_details = S3HeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(s3_details)

    activity_environment.on_heartbeat = track_hearbeat_details

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        max_file_size_mb=max_file_size_mb,
        batch_export_schema=None,
        batch_export_model=model,
    )

    with override_settings(
        # 5MB, the minimum for Multipart uploads
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2,
    ):
        records_exported = await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert records_exported == len(events_to_export_created)

    # Takes a long time to re-read this data from ClickHouse, so we just make sure that:
    # 1. The file exists in S3.
    # 2. We can read it (so, it's a valid file).
    # 3. It has the same length as the events we have created.
    s3_data, s3_keys = await assert_files_in_s3(
        s3_compatible_client=minio_client,
        bucket_name=bucket_name,
        key_prefix=prefix,
        file_format=file_format,
        compression=compression,
        json_columns=("properties", "person_properties", "set", "set_once"),
    )

    assert len(s3_data) == len(events_to_export_created)
    num_files = len(s3_keys)

    def expected_s3_key(
        file_number: int,
        data_interval_start: dt.datetime,
        data_interval_end: dt.datetime,
        file_format: str,
        compression: str,
        max_file_size_mb: int | None,
    ):
        file_extension = FILE_FORMAT_EXTENSIONS[file_format]
        base_key_name = f"{prefix}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}"
        # for backwards compatibility with the old file naming scheme
        if max_file_size_mb is None:
            key_name = base_key_name
        else:
            key_name = f"{base_key_name}-{file_number}"
        key_name = f"{key_name}.{file_extension}"
        if compression:
            compression_extension = COMPRESSION_EXTENSIONS[compression]
            key_name = f"{key_name}.{compression_extension}"
        return key_name

    if max_file_size_mb is None:
        # we only expect 1 file
        assert num_files == 1
    else:
        assert num_files > 1

    expected_keys = [
        expected_s3_key(
            file_number=i,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            file_format=file_format,
            compression=compression,
            max_file_size_mb=max_file_size_mb,
        )
        for i in range(num_files)
    ]
    assert set(expected_keys) == set(s3_keys)

    manifest_key = f"{prefix}/{data_interval_start.isoformat()}-{data_interval_end.isoformat()}_manifest.json"
    # we only expect a manifest file if we have set a max file size
    if max_file_size_mb is None:
        with pytest.raises(minio_client.exceptions.NoSuchKey):
            await read_json_file_from_s3(minio_client, bucket_name, manifest_key)
    else:
        manifest_data: dict | list = await read_json_file_from_s3(minio_client, bucket_name, manifest_key)
        assert isinstance(manifest_data, dict)
        assert manifest_data["files"] == expected_keys

    # check heartbeat details
    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    assert detail.files_uploaded == num_files
    assert detail.upload_state is None


@pytest.mark.parametrize("compression", [None, "gzip"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize("file_format", ["Parquet"])
async def test_insert_into_s3_activity_puts_splitted_parquet_data_into_s3(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    ateam,
):
    """Test that the insert_into_s3_activity function exports uncorrupted parquet data.

    More specifically, we are interested in what happens when there is the need to split
    up a parquet file into multiple parts, so we generate a lot of data for this test.
    """
    prefix = str(uuid.uuid4())

    events_1, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$prop1": 123},
    )

    events_2, _, _ = await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=100000,
        count_outside_range=0,
        count_other_team=0,
        duplicate=False,
        properties={"$prop1": 123},
    )

    events_to_export_created = events_1 + events_2

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2
    ):  # 5MB, the minimum for Multipart uploads
        records_exported = await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert records_exported == len(events_to_export_created)

    # Takes a long time to re-read this data from ClickHouse, so we just make sure that:
    # 1. The file exists in S3.
    # 2. We can read it (so, it's a valid parquet).
    # 3. It has the same length as the events we have created.
    s3_data = await assert_file_in_s3(
        s3_compatible_client=minio_client,
        bucket_name=bucket_name,
        key_prefix=prefix,
        file_format=file_format,
        compression=compression,
        json_columns=("properties", "person_properties", "set", "set_once"),
    )

    assert len(s3_data) == len(events_to_export_created)


@pytest.mark.parametrize("model", [model for model in TEST_S3_MODELS if model is not None])
async def test_insert_into_s3_activity_puts_data_into_s3_using_async(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema,
    generate_test_data,
    ateam,
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
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    prefix = str(uuid.uuid4())

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
    )

    with override_settings(
        BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2,
        ASYNC_ARROW_STREAMING_TEAM_IDS=[str(ateam.pk)],
    ):  # 5MB, the minimum for Multipart uploads
        records_exported = await activity_environment.run(insert_into_s3_activity, insert_inputs)

    events_to_export_created, persons_to_export_created = generate_test_data
    assert (
        records_exported == len(events_to_export_created)
        or records_exported == len(persons_to_export_created)
        or records_exported == len([event for event in events_to_export_created if event["properties"] is not None])
    )

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
        file_format=file_format,
        backfill_details=None,
    )


@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize("file_format", ["invalid"])
async def test_insert_into_s3_activity_fails_on_invalid_file_format(
    clickhouse_client,
    bucket_name,
    minio_client,
    activity_environment,
    compression,
    exclude_events,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    ateam,
):
    """Test the insert_into_s3_activity function fails with an invalid file format."""
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix="any",
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
    )

    with pytest.raises(UnsupportedFileFormatError):
        with override_settings(BATCH_EXPORT_POSTGRES_UPLOAD_CHUNK_SIZE_BYTES=5 * 1024**2):
            await activity_environment.run(insert_into_s3_activity, insert_inputs)


@pytest_asyncio.fixture
async def s3_batch_export(
    ateam,
    s3_key_prefix,
    bucket_name,
    compression,
    interval,
    exclude_events,
    temporal_client,
    encryption,
    file_format,
):
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": s3_key_prefix,
            "aws_access_key_id": "object_storage_root_user",
            "aws_secret_access_key": "object_storage_root_password",
            "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
            "compression": compression,
            "exclude_events": exclude_events,
            "encryption": encryption,
            "kms_key_id": os.getenv("S3_TEST_KMS_KEY_ID") if encryption == "aws:kms" else None,
            "file_format": file_format,
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


@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys(), indirect=True)
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
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
):
    """Test S3BatchExport Workflow end-to-end by using a local MinIO bucket instead of S3.

    The workflow should update the batch export run status to completed and produce the expected
    records to the MinIO bucket.

    We use a BatchExport model to provide accurate inputs to the Workflow and because the Workflow
    will require its prescense in the database when running. This model is indirectly parametrized
    by several fixtures. Refer to them for more information.
    """
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        # Eventually, this setting should be part of the model via some "filters" attribute.
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
        batch_export_model=model,
        exclude_events=exclude_events,
        compression=compression,
        file_format=file_format,
    )


@pytest.mark.parametrize(
    "data_interval_start",
    # This is set to 24 hours before the `data_interval_end` to ensure that the data created is outside the batch
    # interval.
    [dt.datetime.now(tz=dt.UTC).replace(hour=0, minute=0, second=0, microsecond=0) - dt.timedelta(hours=24)],
    indirect=True,
)
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="persons", schema=None)])
async def test_s3_export_workflow_backfill_earliest_persons_with_minio_bucket(
    clickhouse_client,
    minio_client,
    ateam,
    s3_batch_export,
    bucket_name,
    interval,
    compression,
    exclude_events,
    s3_key_prefix,
    file_format,
    data_interval_start,
    data_interval_end,
    model,
    generate_test_data,
):
    """Test a `S3BatchExportWorkflow` backfilling the persons model.

    We expect persons outside the batch interval to also be backfilled (i.e. persons that were updated
    more than an hour ago) when setting `is_earliest_backfill=True`.
    """
    workflow_id = str(uuid.uuid4())
    backfill_details = BackfillDetails(
        backfill_id=str(uuid.uuid4()),
        is_earliest_backfill=True,
        start_at=None,
        end_at=data_interval_end.isoformat(),
    )
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_model=model,
        backfill_details=backfill_details,
        **s3_batch_export.destination.config,
    )
    _, persons = generate_test_data

    # Ensure some data outside batch interval has been created
    assert any(
        data_interval_end - person["_timestamp"].replace(tzinfo=dt.UTC) > dt.timedelta(hours=12) for person in persons
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.data_interval_start is None

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        compression=compression,
        file_format=file_format,
        backfill_details=backfill_details,
    )


@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("compression", [None], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
async def test_s3_export_workflow_with_minio_bucket_without_events(
    clickhouse_client,
    minio_client,
    ateam,
    s3_batch_export,
    bucket_name,
    interval,
    compression,
    exclude_events,
    s3_key_prefix,
    model,
    data_interval_start,
    data_interval_end,
):
    """Test S3BatchExport Workflow end-to-end without any events to export.

    The workflow should update the batch export run status to completed and set 0 as `records_completed`.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(minutes=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"
    assert run.records_completed == 0

    objects = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=s3_key_prefix)
    assert len(objects.get("Contents", [])) == 0


@pytest_asyncio.fixture
async def s3_client(bucket_name, s3_key_prefix):
    """Manage an S3 client to interact with an S3 bucket.

    Yields the client after assuming the test bucket exists. Upon resuming, we delete
    the contents of the bucket under the key prefix we are testing. This opens up the door
    to bugs that could delete all other data in your bucket. I *strongly* recommend
    using a disposable bucket to run these tests or sticking to other tests that use the
    local development MinIO.
    """
    async with aioboto3.Session().client("s3") as s3_client:
        yield s3_client

        await delete_all_from_s3(s3_client, bucket_name, key_prefix=s3_key_prefix)


@pytest.mark.skipif(
    "S3_TEST_BUCKET" not in os.environ or not check_valid_credentials(),
    reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
)
@pytest.mark.parametrize("interval", ["hour", "day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize("compression", [None, "gzip", "brotli"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("encryption", [None, "AES256", "aws:kms"], indirect=True)
@pytest.mark.parametrize("bucket_name", [os.getenv("S3_TEST_BUCKET")], indirect=True)
@pytest.mark.parametrize("model", TEST_S3_MODELS)
@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys(), indirect=True)
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
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
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
    if isinstance(model, BatchExportModel) and model.name == "persons" and exclude_events is not None:
        pytest.skip("Unnecessary test case as person batch export is not affected by 'exclude_events'")

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    destination_config = s3_batch_export.destination.config | {
        "endpoint_url": None,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        **destination_config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Completed"

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=s3_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
        exclude_events=exclude_events,
        include_events=None,
        compression=compression,
        file_format=file_format,
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
@pytest.mark.parametrize("model", [TEST_S3_MODELS[1], TEST_S3_MODELS[3], None])
async def test_s3_export_workflow_with_minio_bucket_and_custom_key_prefix(
    clickhouse_client,
    ateam,
    minio_client,
    bucket_name,
    compression,
    interval,
    s3_batch_export,
    s3_key_prefix,
    data_interval_end,
    data_interval_start,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
):
    """Test the S3BatchExport Workflow end-to-end by specifying a custom key prefix.

    This test is the same as test_s3_export_workflow_with_minio_bucket, but we create events with None as
    inserted_at to assert we properly default to _timestamp. This is relevant for rows inserted before inserted_at
    was added.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=dt.timedelta(seconds=10),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    (events_to_export_created, persons_to_export_created) = generate_test_data
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created) or run.records_completed == len(
        persons_to_export_created
    )

    expected_key_prefix = s3_key_prefix.format(
        table=batch_export_model.name if batch_export_model is not None else "events",
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
        key_prefix=expected_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        compression=compression,
        batch_export_model=model,
    )


class RetryableTestException(Exception):
    """An exception to be raised during tests"""

    pass


async def test_s3_export_workflow_handles_insert_activity_errors(ateam, s3_batch_export, interval):
    """Test S3BatchExport Workflow can handle errors from executing the insert into S3 activity.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_s3_activity")
    async def insert_into_s3_activity_mocked(_: S3InsertInputs) -> str:
        raise RetryableTestException("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_s3_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "FailedRetryable"
    assert run.latest_error == "RetryableTestException: A useful error message"
    assert run.records_completed is None


async def test_s3_export_workflow_handles_insert_activity_non_retryable_errors(ateam, s3_batch_export, interval):
    """Test S3BatchExport Workflow can handle non-retryable errors from executing the insert into S3 activity.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        interval=interval,
        **s3_batch_export.destination.config,
    )

    @activity.defn(name="insert_into_s3_activity")
    async def insert_into_s3_activity_mocked(_: S3InsertInputs) -> str:
        class ParamValidationError(Exception):
            pass

        raise ParamValidationError("A useful error message")

    async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
        async with Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                insert_into_s3_activity_mocked,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await activity_environment.client.execute_workflow(
                    S3BatchExportWorkflow.run,
                    inputs,
                    id=workflow_id,
                    task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 1

    run = runs[0]
    assert run.status == "Failed"
    assert run.latest_error == "ParamValidationError: A useful error message"


@pytest.mark.asyncio
async def test_s3_export_workflow_handles_cancellation(ateam, s3_batch_export, interval):
    """Test that S3 Export Workflow can gracefully handle cancellations when inserting S3 data.

    Currently, this only means we do the right updates to the BatchExportRun model.
    """
    data_interval_end = dt.datetime.fromisoformat("2023-04-25T14:30:00.000000+00:00")

    workflow_id = str(uuid.uuid4())
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
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                mocked_start_batch_export_run,
                never_finish_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await activity_environment.client.start_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
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
base_inputs = {"bucket_name": "test", "region": "test", "team_id": 1}


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
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                file_format="Parquet",
                compression="snappy",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.sz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="gzip",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.gz",
        ),
        (
            S3InsertInputs(
                prefix="/nested/prefix/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                compression="brotli",
                file_format="Parquet",
                **base_inputs,  # type: ignore
            ),
            "nested/prefix/2023-01-01 00:00:00-2023-01-01 01:00:00.parquet.br",
        ),
        (
            S3InsertInputs(
                prefix="/",
                data_interval_start="2023-01-01 00:00:00",
                data_interval_end="2023-01-01 01:00:00",
                max_file_size_mb=1,
                **base_inputs,  # type: ignore
            ),
            "2023-01-01 00:00:00-2023-01-01 01:00:00-0.jsonl",
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
    data_interval_end = TEST_DATA_INTERVAL_END
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
            properties={"$chonky": ("a" * 5 * 2048**2)},
            inserted_at=part_inserted_at,
        )

    heartbeat_details: list[S3HeartbeatDetails] = []

    def track_hearbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details

        s3_details = S3HeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(s3_details)

    activity_environment.on_heartbeat = track_hearbeat_details

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )

    with override_settings(BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=1, CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT=1):
        await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert len(heartbeat_details) > 0

    detail = heartbeat_details[-1]

    # we've uploaded 1 file so we expect the files_uploaded to be 1 and the upload_state to be None
    assert detail.files_uploaded == 1
    assert detail.upload_state is None

    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )


async def test_insert_into_s3_activity_resumes_from_heartbeat(
    clickhouse_client, ateam, bucket_name, s3_batch_export, minio_client, activity_environment, s3_key_prefix
):
    """
    Test that if the insert_into_s3_activity activity fails, it can resume from a heartbeat.

    We mock the upload_part method to raise a `RequestTimeout` error after the first part has been uploaded.
    We then resume from the heartbeat and expect the activity to resume from where it left off.
    """
    data_interval_end = TEST_DATA_INTERVAL_END
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
            properties={"$chonky": ("a" * 5 * 2048**2)},
            inserted_at=part_inserted_at,
        )

    attempt = 0

    class FakeSession(aioboto3.Session):
        @contextlib.asynccontextmanager
        async def client(self, *args, **kwargs):
            client = self._session.create_client(*args, **kwargs)

            async with client as client:
                original_upload_part = client.upload_part

                async def faulty_upload_part(*args, **kwargs):
                    nonlocal attempt

                    attempt = attempt + 1

                    if attempt >= 2:
                        raise botocore.exceptions.ClientError(
                            error_response={
                                "Error": {"Code": "RequestTimeout", "Message": "Oh no!"},
                                "ResponseMetadata": {"MaxAttemptsReached": True, "RetryAttempts": 2},  # type: ignore
                            },
                            operation_name="UploadPart",
                        )
                    else:
                        return await original_upload_part(*args, **kwargs)

                client.upload_part = faulty_upload_part

                yield client

    heartbeat_details: list[S3HeartbeatDetails] = []

    def track_hearbeat_details(*details):
        """Record heartbeat details received."""
        nonlocal heartbeat_details

        s3_details = S3HeartbeatDetails.from_activity_details(details)
        heartbeat_details.append(s3_details)

    activity_environment.on_heartbeat = track_hearbeat_details

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )

    with (
        override_settings(BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=1, CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT=1),
        mock.patch("posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session", FakeSession),
    ):
        with pytest.raises(IntermittentUploadPartTimeoutError):
            # we expect this to raise an exception
            await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert len(heartbeat_details) > 0

    detail = heartbeat_details[-1]

    # we expect to have only uploaded part 1 of first file
    assert detail.files_uploaded == 0
    assert detail.upload_state is not None
    assert detail.upload_state.upload_id is not None
    assert len(detail.upload_state.parts) == 1

    assert len(detail.done_ranges) == 1

    # now we resume from the heartbeat
    previous_info = asdict(activity_environment.info)
    previous_info["heartbeat_details"] = detail.serialize_details()
    new_info = activity.Info(
        **previous_info,
    )
    activity_environment.info = new_info
    with override_settings(BATCH_EXPORT_S3_UPLOAD_CHUNK_SIZE_BYTES=1, CLICKHOUSE_MAX_BLOCK_SIZE_DEFAULT=1):
        await activity_environment.run(insert_into_s3_activity, insert_inputs)

    assert len(heartbeat_details) > 0
    detail = heartbeat_details[-1]
    # we expect to have uploaded the file now
    assert detail.files_uploaded == 1
    assert detail.upload_state is None
    assert len(detail.done_ranges) == 1
    assert detail.done_ranges[0] == (data_interval_start, data_interval_end)

    await assert_clickhouse_records_in_s3(
        s3_compatible_client=minio_client,
        clickhouse_client=clickhouse_client,
        bucket_name=bucket_name,
        key_prefix=s3_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        # When we resume from a heartbeat, we expect duplicates (the last done range will be re-exported)
        allow_duplicates=True,
    )


async def test_s3_multi_part_upload_raises_retryable_exception(bucket_name, s3_key_prefix):
    """Test a retryable exception is raised instead of a `RequestTimeout`.

    Even though they should be retryable, `RequestTimeout`s are wrapped by `ClientError`, which
    are all non-retryable. So, we assert our own exception is raised instead.
    """
    s3_upload = S3MultiPartUpload(
        bucket_name=bucket_name,
        key=s3_key_prefix,
        encryption=None,
        kms_key_id=None,
        region_name="us-east-1",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )

    async def faulty_upload_part(*args, **kwargs):
        raise botocore.exceptions.ClientError(
            error_response={
                "Error": {"Code": "RequestTimeout", "Message": "Oh no!"},
                "ResponseMetadata": {"MaxAttemptsReached": True, "RetryAttempts": 2},  # type: ignore
            },
            operation_name="UploadPart",
        )

    class FakeSession(aioboto3.Session):
        @contextlib.asynccontextmanager
        async def client(self, *args, **kwargs):
            client = self._session.create_client(*args, **kwargs)
            client.upload_part = faulty_upload_part

            yield client

    s3_upload._session = FakeSession()

    with pytest.raises(IntermittentUploadPartTimeoutError):
        await s3_upload.upload_part(io.BytesIO(b"1010"), rewind=False)  # type: ignore


async def test_s3_multi_part_upload_raises_exception_if_invalid_endpoint(bucket_name, s3_key_prefix):
    """Test a InvalidS3EndpointError is raised if the endpoint is invalid."""
    s3_upload = S3MultiPartUpload(
        bucket_name=bucket_name,
        key=s3_key_prefix,
        encryption=None,
        kms_key_id=None,
        region_name="us-east-1",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url="some-invalid-endpoint",
    )

    with pytest.raises(InvalidS3EndpointError):
        await s3_upload.start()


@pytest.mark.parametrize("model", [TEST_S3_MODELS[1], TEST_S3_MODELS[3], None])
async def test_s3_export_workflow_with_request_timeouts(
    clickhouse_client,
    ateam,
    minio_client,
    bucket_name,
    interval,
    s3_batch_export,
    s3_key_prefix,
    data_interval_end,
    data_interval_start,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
):
    """Test the S3BatchExport Workflow end-to-end when a `RequestTimeout` occurs.

    We run the S3 batch export workflow with a mocked session that will raise a `ClientError` due
    to a `RequestTimeout` on the first run of the batch export. The second run should work normally.
    """
    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    raised = 0

    class FakeSession(aioboto3.Session):
        @contextlib.asynccontextmanager
        async def client(self, *args, **kwargs):
            client = self._session.create_client(*args, **kwargs)

            async with client as client:
                original_upload_part = client.upload_part

                async def faulty_upload_part(*args, **kwargs):
                    nonlocal raised

                    if raised < 5:
                        raised = raised + 1
                        raise botocore.exceptions.ClientError(
                            error_response={
                                "Error": {"Code": "RequestTimeout", "Message": "Oh no!"},
                                "ResponseMetadata": {"MaxAttemptsReached": True, "RetryAttempts": 2},  # type: ignore
                            },
                            operation_name="UploadPart",
                        )
                    else:
                        return await original_upload_part(*args, **kwargs)

                client.upload_part = faulty_upload_part

                yield client

    class DoNotRetryPolicy(RetryPolicy):
        def __init__(self, *args, **kwargs):
            kwargs["maximum_attempts"] = 1
            super().__init__(*args, **kwargs)

    workflow_id = str(uuid.uuid4())
    inputs = S3BatchExportInputs(
        team_id=ateam.pk,
        batch_export_id=str(s3_batch_export.id),
        data_interval_end=data_interval_end.isoformat(),
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        interval=interval,
        **s3_batch_export.destination.config,
    )

    async with (
        await WorkflowEnvironment.start_time_skipping() as activity_environment,
        Worker(
            activity_environment.client,
            task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
            workflows=[S3BatchExportWorkflow],
            activities=[
                start_batch_export_run,
                insert_into_s3_activity,
                finish_batch_export_run,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        with (
            mock.patch("posthog.temporal.batch_exports.s3_batch_export.aioboto3.Session", FakeSession),
            mock.patch("posthog.temporal.batch_exports.batch_exports.RetryPolicy", DoNotRetryPolicy),
        ):
            await activity_environment.client.execute_workflow(
                S3BatchExportWorkflow.run,
                inputs,
                id=workflow_id,
                task_queue=constants.BATCH_EXPORTS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=2),
                execution_timeout=dt.timedelta(minutes=2),
            )

    runs = await afetch_batch_export_runs(batch_export_id=s3_batch_export.id)
    assert len(runs) == 2
    # Sort by `last_updated_at` as earlier run should be the failed run.
    runs.sort(key=lambda r: r.last_updated_at)

    run = runs[0]
    (events_to_export_created, persons_to_export_created) = generate_test_data
    assert run.status == "FailedRetryable"
    assert run.records_completed is None
    assert (
        run.latest_error
        == "IntermittentUploadPartTimeoutError: An intermittent `RequestTimeout` was raised while attempting to upload part 1"
    )

    run = runs[1]
    (events_to_export_created, persons_to_export_created) = generate_test_data
    assert run.status == "Completed"
    assert run.records_completed == len(events_to_export_created) or run.records_completed == len(
        persons_to_export_created
    )

    assert runs[0].data_interval_end == runs[1].data_interval_end

    expected_key_prefix = s3_key_prefix.format(
        table=batch_export_model.name if batch_export_model is not None else "events",
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
        key_prefix=expected_key_prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        batch_export_model=model,
    )


@pytest.mark.parametrize("interval", ["day", "every 5 minutes"], indirect=True)
@pytest.mark.parametrize(
    "model",
    [
        BatchExportModel(name="events", schema=None),
    ],
)
@pytest.mark.parametrize("is_backfill", [False, True])
@pytest.mark.parametrize("backfill_within_last_6_days", [False, True])
@pytest.mark.parametrize("data_interval_end", [TEST_DATA_INTERVAL_END])
async def test_insert_into_s3_activity_executes_the_expected_query_for_events_model(
    clickhouse_client,
    bucket_name,
    minio_client,
    interval,
    activity_environment,
    data_interval_start,
    data_interval_end,
    generate_test_data,
    ateam,
    model: BatchExportModel,
    is_backfill: bool,
    backfill_within_last_6_days: bool,
):
    """Test that the insert_into_s3_activity executes the expected ClickHouse query when the model is an events model.

    The query used for the events model is quite complex, and depends on a number of factors:
    - If it's a backfill
    - How far in the past we're backfilling
    - If it's a 5 min batch export
    """

    if not is_backfill and backfill_within_last_6_days:
        pytest.skip("No need to test backfill within last 6 days for non-backfill")

    expected_table = "distributed_events_recent"
    if not is_backfill and interval == "every 5 minutes":
        expected_table = "events_recent"
    elif is_backfill and not backfill_within_last_6_days:
        expected_table = "events"

    if backfill_within_last_6_days:
        backfill_start_at = (data_interval_end - dt.timedelta(days=3)).isoformat()
    else:
        backfill_start_at = (data_interval_end - dt.timedelta(days=10)).isoformat()

    compression = None
    exclude_events = None
    file_format = "JSONLines"
    prefix = str(uuid.uuid4())

    insert_inputs = S3InsertInputs(
        bucket_name=bucket_name,
        region="us-east-1",
        prefix=prefix,
        team_id=ateam.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        compression=compression,
        exclude_events=exclude_events,
        file_format=file_format,
        batch_export_schema=None,
        batch_export_model=model,
        is_backfill=is_backfill,
        backfill_details=BackfillDetails(
            backfill_id=str(uuid.uuid4()),
            start_at=backfill_start_at,
            end_at=data_interval_end,
            is_earliest_backfill=False,
        )
        if is_backfill
        else None,
    )

    class MockClickHouseClient:
        """Helper class to mock ClickHouse client."""

        def __init__(self):
            self.mock_client = mock.AsyncMock(spec=ClickHouseClient)
            self.mock_client_cm = mock.AsyncMock()
            self.mock_client_cm.__aenter__.return_value = self.mock_client
            self.mock_client_cm.__aexit__.return_value = None

            # Set up the mock to return our async iterator
            self.mock_client.astream_query_as_arrow.return_value = self._create_record_batch_iterator()

        def expect_select_from_table(self, table_name: str) -> None:
            """Assert that the executed query selects from the expected table.

            Args:
                table_name: The name of the table to check for in the FROM clause.

            The method handles different formatting of the FROM clause, including newlines
            and varying amounts of whitespace.
            """
            assert self.mock_client.astream_query_as_arrow.call_count == 1
            call_args = self.mock_client.astream_query_as_arrow.call_args
            query = call_args[0][0]  # First positional argument of the first call

            # Create a pattern that matches "FROM" followed by optional whitespace/newlines and then the table name
            pattern = rf"FROM\s+{re.escape(table_name)}"
            assert re.search(pattern, query, re.IGNORECASE), f"Query does not select FROM {table_name}"

        @staticmethod
        def _create_test_record_batch() -> pa.RecordBatch:
            """Create a record batch with test data."""
            schema = pa.schema(
                [
                    ("team_id", pa.int64()),
                    ("timestamp", pa.timestamp("us")),
                    ("event", pa.string()),
                    ("distinct_id", pa.string()),
                    ("uuid", pa.string()),
                    ("_inserted_at", pa.timestamp("us")),
                    ("created_at", pa.timestamp("us")),
                    ("elements_chain", pa.string()),
                    ("person_id", pa.string()),
                    ("properties", pa.string()),  # JSON string
                    ("person_properties", pa.string()),  # JSON string
                    ("set", pa.string()),  # JSON string
                    ("set_once", pa.string()),  # JSON string
                ]
            )

            now = dt.datetime.now(dt.UTC)
            arrays = [
                pa.array([1]),  # team_id
                pa.array([now]),  # timestamp
                pa.array(["test_event"]),  # event
                pa.array(["test_distinct_id"]),  # distinct_id
                pa.array([str(uuid.uuid4())]),  # uuid
                pa.array([now]),  # _inserted_at
                pa.array([now]),  # created_at
                pa.array(["div > button"]),  # elements_chain
                pa.array([str(uuid.uuid4())]),  # person_id
                pa.array([json.dumps({"prop1": "value1"})]),  # properties
                pa.array([json.dumps({"person_prop1": "value1"})]),  # person_properties
                pa.array([json.dumps({"set1": "value1"})]),  # set
                pa.array([json.dumps({"set_once1": "value1"})]),  # set_once
            ]
            return pa.RecordBatch.from_arrays(arrays, schema=schema)

        async def _create_record_batch_iterator(self):
            """Create an async iterator that yields a single record batch with test data."""
            yield self._create_test_record_batch()

    @contextlib.contextmanager
    def mock_clickhouse_client():
        """Context manager to mock ClickHouse client."""
        mock_client = MockClickHouseClient()
        with patch("posthog.temporal.batch_exports.spmc.get_client", return_value=mock_client.mock_client_cm):
            yield mock_client

    with mock_clickhouse_client() as mock_client:
        await activity_environment.run(insert_into_s3_activity, insert_inputs)
        mock_client.expect_select_from_table(expected_table)
