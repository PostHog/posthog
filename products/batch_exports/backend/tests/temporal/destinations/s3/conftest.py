import uuid

import pytest

from django.conf import settings

from posthog.temporal.tests.utils.models import acreate_batch_export, adelete_batch_export

from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db]

TEST_ROOT_BUCKET = "test-batch-exports"


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


@pytest.fixture
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

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="")

        await minio_client.delete_bucket(Bucket=bucket_name)


@pytest.fixture
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
            "kms_key_id": None,
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
