import json
import uuid

import pytest
from unittest import mock

from django.conf import settings

import aioboto3
import botocore.exceptions

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ClientErrorGroup,
    upload_manifest_file,
)
from products.batch_exports.backend.temporal.temporary_file import remove_escaped_whitespace_recursive
from products.batch_exports.backend.tests.temporal.utils.s3 import delete_all_from_s3

TEST_ROOT_BUCKET = "test-batch-exports"


@pytest.mark.parametrize(
    "value,expected",
    [
        ([1, 2, 3], [1, 2, 3]),
        ("hi\t\n\r\f\bhi", "hi hi"),
        ([["\t\n\r\f\b"]], [[""]]),
        (("\t\n\r\f\b",), ("",)),
        ({"\t\n\r\f\b"}, {""}),
        ({"key": "\t\n\r\f\b"}, {"key": ""}),
        ({"key": ["\t\n\r\f\b"]}, {"key": [""]}),
    ],
)
def test_remove_escaped_whitespace_recursive(value, expected):
    """Test we remove some whitespace values."""
    assert remove_escaped_whitespace_recursive(value) == expected


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
    async with aioboto3.Session().client(
        "s3",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    ) as minio_client:
        await minio_client.create_bucket(Bucket=bucket_name)

        yield minio_client

        await delete_all_from_s3(minio_client, bucket_name, key_prefix="")

        await minio_client.delete_bucket(Bucket=bucket_name)


async def test_upload_manifest_file(minio_client, bucket_name):
    """Test the a correctly formatted manifest is uploaded with the necessary contents."""
    test_prefix = uuid.uuid4()

    files_uploaded = []
    for file_number in range(3):
        key = f"{test_prefix}/file_{file_number}"
        await minio_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=b"0",
        )
        files_uploaded.append(key)

    manifest_key = f"/{test_prefix}/manifest.json"
    await upload_manifest_file(
        bucket=bucket_name,
        region_name="us-east-1",
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        files_uploaded=files_uploaded,
        manifest_key=manifest_key,
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
    )

    obj = await minio_client.get_object(Bucket=bucket_name, Key=manifest_key)
    body = await obj["Body"].read()
    loaded = json.loads(body)

    all_file_entries = {entry["url"] for entry in loaded["entries"]}
    for file_uploaded in files_uploaded:
        assert f"s3://{bucket_name}/{file_uploaded}" in all_file_entries

    total_content_length = sum(entry["meta"]["content_length"] for entry in loaded["entries"])
    assert total_content_length == 3


async def test_upload_manifest_file_raises_on_client_error(minio_client, bucket_name):
    """Test a ClientErrorGroup is raised when tasks fail."""
    test_prefix = uuid.uuid4()

    # We don't need to actually upload any files for this, as we will make list_objects_v2 fail.
    files_uploaded = [f"{test_prefix}/file_{file_number}" for file_number in range(3)]

    manifest_key = f"/{test_prefix}/manifest.json"

    mock_client = mock.MagicMock()
    mock_client.list_objects_v2.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Bad user!"}}, "list_objects_v2"
    )

    mock_context_manager = mock.MagicMock()
    mock_context_manager.__aenter__.return_value = mock_client
    mock_context_manager.__aexit__.return_value = None

    mock_session_instance = mock.MagicMock()
    mock_session_instance.client.return_value = mock_context_manager

    with mock.patch(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.aioboto3.Session"
    ) as mock_session_class:
        mock_session_class.return_value = mock_session_instance

        with pytest.raises(ClientErrorGroup) as exc_info:
            await upload_manifest_file(
                bucket=bucket_name,
                region_name="us-east-1",
                aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
                files_uploaded=files_uploaded,
                manifest_key=manifest_key,
                endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
            )
        assert all(isinstance(exc, botocore.exceptions.ClientError) for exc in exc_info.value.exceptions)
        assert exc_info.value.ops == {"list_objects_v2": {"AccessDenied"}}  # type: ignore
