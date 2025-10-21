import uuid
import functools

import pytest

from django.conf import settings

import aioboto3

from products.batch_exports.backend.api.destination_tests.s3 import S3EnsureBucketTestStep, Status

pytestmark = [pytest.mark.asyncio]

TEST_ROOT_BUCKET = "test-destination-tests"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    """Name for a test S3 bucket."""
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{str(uuid.uuid4())}"


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

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="/")

        await minio_client.delete_bucket(Bucket=bucket_name)


async def delete_all_from_s3(minio_client, bucket_name: str, key_prefix: str):
    """Delete all objects in bucket_name under key_prefix."""
    response = await minio_client.list_objects_v2(Bucket=bucket_name, Prefix=key_prefix)

    if "Contents" in response:
        for obj in response["Contents"]:
            if "Key" in obj:
                await minio_client.delete_object(Bucket=bucket_name, Key=obj["Key"])


async def test_s3_check_bucket_exists_test_step(bucket_name, minio_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name=bucket_name,
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.PASSED
    assert result.message is None


async def test_s3_check_bucket_exists_test_step_without_bucket(minio_client):
    test_step = S3EnsureBucketTestStep(
        bucket_name="some-other-bucket",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )
    result = await test_step.run()

    assert result.status == Status.FAILED
    assert result.message == "Bucket 'some-other-bucket' does not exist or we don't have permissions to use it"


@pytest.mark.parametrize("step", [S3EnsureBucketTestStep()])
async def test_test_steps_fail_if_not_configured(step):
    result = await step.run()
    assert result.status == Status.FAILED
    assert result.message == "The test step cannot run as it's not configured."
