import os
import uuid
import asyncio

import pytest

import aioboto3
import botocore.exceptions

from posthog.batch_exports.service import BatchExportInsertInputs, BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.events import generate_test_events_in_clickhouse

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ConnectionParameters,
    CopyParameters,
    Credentials,
    RedshiftCopyInputs,
    S3StageBucketParameters,
    TableParameters,
    copy_into_redshift_activity_from_stage,
    redshift_default_fields,
)
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    BatchExportInsertIntoInternalStageInputs,
    insert_into_internal_stage_activity,
)
from products.batch_exports.backend.tests.temporal.destinations.redshift.utils import (
    MISSING_REQUIRED_ENV_VARS,
    TEST_MODELS,
    assert_clickhouse_records_in_redshift,
)


async def check_valid_credentials() -> bool:
    """Check if there are valid AWS credentials in the environment."""
    session = aioboto3.Session()
    async with session.client("sts") as sts:
        try:
            await sts.get_caller_identity()
        except botocore.exceptions.ClientError:
            return False
        else:
            return True


def has_valid_credentials() -> bool:
    """Synchronous wrapper around check_valid_credentials."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(check_valid_credentials())


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        "S3_TEST_BUCKET" not in os.environ or not has_valid_credentials() or MISSING_REQUIRED_ENV_VARS,
        reason="AWS credentials not set in environment or missing S3_TEST_BUCKET variable",
    ),
]


@pytest.fixture
def bucket_name() -> str:
    """Name for a test S3 bucket."""
    test_bucket = os.getenv("S3_TEST_BUCKET")

    if not test_bucket:
        raise ValueError("Missing S3_TEST_BUCKET environment variable")

    return test_bucket


@pytest.fixture
def bucket_region() -> str:
    """Region for a test S3 bucket."""
    bucket_region = os.getenv("AWS_REGION")

    if not bucket_region:
        raise ValueError("Missing AWS region environment variable")

    return bucket_region


@pytest.fixture
def aws_credentials() -> Credentials:
    aws_access_key_id, aws_secret_access_key = os.getenv("AWS_ACCESS_KEY_ID"), os.getenv("AWS_SECRET_ACCESS_KEY")

    if not aws_access_key_id or not aws_secret_access_key:
        raise ValueError("Missing AWS credentials")

    return Credentials(aws_access_key_id, aws_secret_access_key)


async def delete_all_from_s3(s3_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await s3_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


@pytest.fixture
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


async def _run_activity(
    activity_environment,
    redshift_connection,
    clickhouse_client,
    redshift_config,
    team,
    data_interval_start,
    data_interval_end,
    table_name: str,
    bucket_name: str,
    bucket_region: str,
    key_prefix: str,
    credentials: Credentials,
    properties_data_type: str,
    batch_export_model: BatchExportModel | None = None,
    batch_export_schema: BatchExportSchema | None = None,
    exclude_events: list[str] | None = None,
    include_events: list[str] | None = None,
    sort_key: str = "event",
    expected_fields=None,
    expect_duplicates: bool = False,
):
    """Helper function to run Redshift main COPY activity and assert records exported.

    This allows using a single function to test both versions of the pipeline.
    """
    batch_export_inputs = BatchExportInsertInputs(
        team_id=team.pk,
        data_interval_start=data_interval_start.isoformat(),
        data_interval_end=data_interval_end.isoformat(),
        exclude_events=exclude_events,
        include_events=include_events,
        run_id=None,
        backfill_details=None,
        is_backfill=False,
        batch_export_model=batch_export_model,
        batch_export_schema=batch_export_schema,
        batch_export_id=str(uuid.uuid4()),
        destination_default_fields=redshift_default_fields(),
    )
    connection_parameters = ConnectionParameters(
        user=redshift_config["user"],
        password=redshift_config["password"],
        host=redshift_config["host"],
        port=redshift_config["port"],
        database=redshift_config["database"],
    )
    table_parameters = TableParameters(
        schema_name=redshift_config["schema"],
        name=table_name,
        properties_data_type=properties_data_type,
    )

    copy_parameters = CopyParameters(
        s3_bucket=S3StageBucketParameters(
            name=bucket_name,
            region_name=bucket_region,
            credentials=credentials,
        ),
        s3_key_prefix=key_prefix,
        authorization=credentials,
    )

    copy_inputs = RedshiftCopyInputs(
        batch_export=batch_export_inputs,
        connection=connection_parameters,
        table=table_parameters,
        copy=copy_parameters,
    )

    assert copy_inputs.batch_export.batch_export_id is not None
    await activity_environment.run(
        insert_into_internal_stage_activity,
        BatchExportInsertIntoInternalStageInputs(
            team_id=copy_inputs.batch_export.team_id,
            batch_export_id=copy_inputs.batch_export.batch_export_id,
            data_interval_start=copy_inputs.batch_export.data_interval_start,
            data_interval_end=copy_inputs.batch_export.data_interval_end,
            exclude_events=copy_inputs.batch_export.exclude_events,
            include_events=None,
            run_id=None,
            backfill_details=None,
            batch_export_model=copy_inputs.batch_export.batch_export_model,
            batch_export_schema=copy_inputs.batch_export.batch_export_schema,
            destination_default_fields=redshift_default_fields(),
        ),
    )
    result = await activity_environment.run(copy_into_redshift_activity_from_stage, copy_inputs)

    await assert_clickhouse_records_in_redshift(
        redshift_connection=redshift_connection,
        clickhouse_client=clickhouse_client,
        schema_name=redshift_config["schema"],
        table_name=table_name,
        team_id=team.pk,
        date_ranges=[(data_interval_start, data_interval_end)],
        batch_export_model=batch_export_model or batch_export_schema,
        exclude_events=exclude_events,
        properties_data_type=properties_data_type,
        sort_key=sort_key,
        expected_fields=expected_fields,
        copy=True,
    )

    return result


@pytest.mark.parametrize("exclude_events", [None, ["test-exclude"]], indirect=True)
@pytest.mark.parametrize("properties_data_type", ["super", "varchar"], indirect=True)
@pytest.mark.parametrize("model", TEST_MODELS)
async def test_copy_into_redshift_activity_inserts_data_into_redshift_table(
    clickhouse_client,
    activity_environment,
    psycopg_connection,
    redshift_config,
    bucket_name,
    bucket_region,
    exclude_events,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
    data_interval_start,
    data_interval_end,
    properties_data_type,
    aws_credentials,
    ateam,
):
    """Test that the copy_into_redshift_activity function inserts data into a Redshift table."""
    if (
        isinstance(model, BatchExportModel)
        and (model.name == "persons" or model.name == "sessions")
        and exclude_events is not None
    ):
        pytest.skip(f"Unnecessary test case as {model.name} batch export is not affected by 'exclude_events'")

    await generate_test_events_in_clickhouse(
        client=clickhouse_client,
        team_id=ateam.pk,
        event_name="test-funny-props-{i}",
        start_time=data_interval_start,
        end_time=data_interval_end,
        count=10,
        properties={
            "$browser": "Chrome",
            "$os": "Mac OS X",
            "whitespace": "hi\t\n\r\f\bhi",
            "nested_whitespace": {"whitespace": "hi\t\n\r\f\bhi"},
            "sequence": {"mucho_whitespace": ["hi", "hi\t\n\r\f\bhi", "hi\t\n\r\f\bhi", "hi"]},
            "multi-byte": "é",
        },
        person_properties={"utm_medium": "referral", "$initial_os": "Linux"},
    )

    batch_export_schema: BatchExportSchema | None = None
    batch_export_model: BatchExportModel | None = None
    if isinstance(model, BatchExportModel):
        batch_export_model = model
    elif model is not None:
        batch_export_schema = model

    table_name = f"test_copy_activity_table__{ateam.pk}"

    sort_key = "event"
    if batch_export_model is not None:
        if batch_export_model.name == "persons":
            sort_key = "person_id"
        elif batch_export_model.name == "sessions":
            sort_key = "session_id"

    await _run_activity(
        activity_environment,
        redshift_connection=psycopg_connection,
        clickhouse_client=clickhouse_client,
        team=ateam,
        table_name=table_name,
        bucket_name=bucket_name,
        bucket_region=bucket_region,
        key_prefix="/test-copy-redshift-batch-export",
        credentials=aws_credentials,
        properties_data_type=properties_data_type,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        exclude_events=exclude_events,
        batch_export_schema=batch_export_schema,
        batch_export_model=batch_export_model,
        redshift_config=redshift_config,
        sort_key=sort_key,
    )
