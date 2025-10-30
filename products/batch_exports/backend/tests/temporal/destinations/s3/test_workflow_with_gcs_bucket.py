import os

import pytest

import aioboto3

from posthog.batch_exports.service import BatchExportModel, BatchExportSchema
from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.tests.temporal.destinations.s3.utils import run_s3_batch_export_workflow
from products.batch_exports.backend.tests.temporal.utils.s3 import delete_all_from_s3


def has_valid_gcs_credentials() -> bool:
    return (
        "GCS_TEST_BUCKET" in os.environ and "AWS_ACCESS_KEY_ID" in os.environ and "AWS_SECRET_ACCESS_KEY" in os.environ
    )


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.django_db,
    pytest.mark.skipif(
        not has_valid_gcs_credentials(),
        reason="GCS credentials (AWS keys) not set in environment or missing GCS_TEST_BUCKET variable",
    ),
]


@pytest.fixture
async def s3_client(bucket_name, s3_key_prefix):
    """Manage an S3 client to interact with a GCS bucket.

    Yields the client after assuming the test bucket exists. Upon resuming, we delete
    the contents of the bucket under the key prefix we are testing. This opens up the door
    to bugs that could delete all other data in your bucket. I *strongly* recommend
    using a disposable bucket to run these tests or sticking to other tests that use the
    local development MinIO.
    """
    async with aioboto3.Session().client("s3", endpoint_url="https://storage.googleapis.com") as s3_client:
        yield s3_client

        await delete_all_from_s3(s3_client, bucket_name, key_prefix=s3_key_prefix)


@pytest.fixture
async def gcs_batch_export(
    ateam,
    s3_key_prefix,
    bucket_name,
    compression,
    interval,
    exclude_events,
    temporal_client,
    file_format,
):
    assert bucket_name
    destination_data = {
        "type": "S3",
        "config": {
            "bucket_name": bucket_name,
            "region": "us-east-1",
            "prefix": s3_key_prefix,
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
            "endpoint_url": "https://storage.googleapis.com",
            "compression": compression,
            "exclude_events": exclude_events,
            "encryption": None,
            "file_format": file_format,
        },
    }

    batch_export_data = {
        "name": "my-gcs-bucket-destination",
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


@pytest.mark.parametrize("file_format", FILE_FORMAT_EXTENSIONS.keys(), indirect=True)
@pytest.mark.parametrize("compression", [*COMPRESSION_EXTENSIONS.keys(), None], indirect=True)
@pytest.mark.parametrize("model", [BatchExportModel(name="events", schema=None)])
@pytest.mark.parametrize("interval", ["hour"], indirect=True)
@pytest.mark.parametrize("exclude_events", [None], indirect=True)
@pytest.mark.parametrize("bucket_name", [os.getenv("GCS_TEST_BUCKET")], indirect=True)
async def test_s3_export_workflow_with_gcs_bucket_with_various_file_formats(
    s3_client,
    clickhouse_client,
    interval,
    gcs_batch_export,
    bucket_name,
    compression,
    ateam,
    file_format,
    data_interval_start,
    data_interval_end,
    model: BatchExportModel | BatchExportSchema | None,
    generate_test_data,
):
    """Test S3 Export Workflow end-to-end by using a GCS bucket.

    The GCS_BUCKET_NAME environment variable is used to set the name of the bucket for this test.
    This test will be skipped if the GCS_BUCKET_NAME environment variable is not set.

    The workflow should update the batch export run status to completed and produce the expected
    records to the GCS bucket.

    Note: GCS does not support server-side encryption via the S3 API like AWS does,
    so we only test with encryption=None.

    We basically want to test that we can interact with a GCS bucket and therefore don't run this test with all
    permutations of model, file format, compression, and encryption, etc.
    """

    if compression and compression not in SUPPORTED_COMPRESSIONS[file_format]:
        pytest.skip(f"Compression {compression} is not supported for file format {file_format}")

    await run_s3_batch_export_workflow(
        model=model,
        ateam=ateam,
        batch_export_id=str(gcs_batch_export.id),
        s3_destination_config=gcs_batch_export.destination.config,
        interval=interval,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        clickhouse_client=clickhouse_client,
        s3_client=s3_client,
    )
