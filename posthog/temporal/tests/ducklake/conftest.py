import uuid
import functools

import pytest

from django.conf import settings

import aioboto3
import pytest_asyncio

TEST_ROOT_BUCKET = "test-ducklake"
SESSION = aioboto3.Session()
create_test_client = functools.partial(SESSION.client, endpoint_url=settings.OBJECT_STORAGE_ENDPOINT)


@pytest.fixture
def bucket_name(request) -> str:
    try:
        return request.param
    except AttributeError:
        return f"{TEST_ROOT_BUCKET}-{uuid.uuid4()}"


@pytest_asyncio.fixture
async def minio_client(bucket_name):
    async with create_test_client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
    ) as client:
        try:
            await client.head_bucket(Bucket=bucket_name)
        except Exception:
            await client.create_bucket(Bucket=bucket_name)

        yield client
