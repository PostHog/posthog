from django.conf import settings

import pytest_asyncio

from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3


@pytest_asyncio.fixture
async def object_storage_client():
    """Manage an S3 client to interact with a local object storage bucket."""
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as object_storage_client:
        yield object_storage_client

        await delete_all_from_s3(object_storage_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")
