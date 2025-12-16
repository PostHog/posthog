import pytest

from django.conf import settings

from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    get_base_s3_staging_folder,
    get_s3_staging_folder,
)
from products.batch_exports.backend.temporal.pipeline.producer import Producer
from products.batch_exports.backend.tests.temporal.utils.s3 import create_test_client, delete_all_from_s3


@pytest.fixture
async def minio_client():
    """Manage an S3 client to interact with a MinIO bucket."""
    async with create_test_client(
        "s3",
        aws_access_key_id="object_storage_root_user",
        aws_secret_access_key="object_storage_root_password",
    ) as minio_client:
        await delete_all_from_s3(minio_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")
        yield minio_client
        await delete_all_from_s3(minio_client, settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET, key_prefix="")


async def _create_s3_files(
    s3_client, batch_export_id, data_interval_start, data_interval_end, attempts, num_files_per_attempt
):
    """Create some S3 files with different attempt numbers."""
    keys = []
    for attempt_number in range(1, attempts + 1):
        key_prefix = get_s3_staging_folder(
            batch_export_id=batch_export_id,
            data_interval_start=data_interval_start,
            data_interval_end=data_interval_end,
            attempt_number=attempt_number,
        )
        for file_number in range(1, num_files_per_attempt + 1):
            key = f"{key_prefix}/export_{file_number}.arrow"
            keys.append(key)
            await s3_client.put_object(
                Bucket=settings.BATCH_EXPORT_INTERNAL_STAGING_BUCKET,
                Key=key,
                Body=b"test",
            )
    return keys


async def test_producer_list_s3_files(minio_client):
    batch_export_id = "test_producer_list_s3_files"
    data_interval_start = "2026-01-01"
    data_interval_end = "2026-01-02"
    base_folder = get_base_s3_staging_folder(
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
    )

    created_keys = await _create_s3_files(
        s3_client=minio_client,
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        attempts=3,
        num_files_per_attempt=3,
    )
    assert len(created_keys) == 9

    producer = Producer()
    keys, common_prefix = await producer._list_s3_files(minio_client, base_folder)

    assert len(keys) == 3
    expected_folder = get_s3_staging_folder(
        batch_export_id=batch_export_id,
        data_interval_start=data_interval_start,
        data_interval_end=data_interval_end,
        attempt_number=3,
    )
    assert common_prefix == f"{expected_folder}/"
    assert set(keys) == {
        f"{expected_folder}/export_1.arrow",
        f"{expected_folder}/export_2.arrow",
        f"{expected_folder}/export_3.arrow",
    }
