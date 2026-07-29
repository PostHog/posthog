from django.conf import settings

import pytest_asyncio

from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3


@pytest_asyncio.fixture
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket."""
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        yield minio_client

        await delete_all_from_s3(minio_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")
