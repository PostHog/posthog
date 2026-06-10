import json
import uuid
from typing import Any

import pytest
from unittest import mock

from django.conf import settings

import psycopg
import aioboto3
import pytest_asyncio
import botocore.exceptions

from products.batch_exports.backend.service import AWSCredentials
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    ClientErrorGroup,
    InsufficientS3PermissionsError,
    RedshiftS3CopyError,
    check_and_raise_redshift_copy_error,
    is_s3_read_access_denied,
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


@pytest_asyncio.fixture
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


def _mock_s3_session_with_head_object(head_object: mock.AsyncMock) -> mock.MagicMock:
    """Build a mocked aioboto3 Session whose S3 client uses the given head_object mock."""
    mock_client = mock.MagicMock()
    mock_client.head_object = head_object

    mock_context_manager = mock.MagicMock()
    mock_context_manager.__aenter__.return_value = mock_client
    mock_context_manager.__aexit__.return_value = None

    mock_session_instance = mock.MagicMock()
    mock_session_instance.client.return_value = mock_context_manager
    return mock_session_instance


@pytest.mark.parametrize(
    "error_code,status_code,expected",
    [
        ("AccessDenied", 403, True),
        ("403", 403, True),
        (None, None, False),
        ("404", 404, False),
    ],
)
async def test_is_s3_read_access_denied(error_code, status_code, expected):
    """Test we report read access as denied only on a 403/AccessDenied HEAD."""
    if error_code is None:
        head_object = mock.AsyncMock(return_value={})
    else:
        # Typed as Any to skip the botocore response TypedDict's required-key checks.
        response: Any = {"Error": {"Code": error_code}, "ResponseMetadata": {"HTTPStatusCode": status_code}}
        head_object = mock.AsyncMock(side_effect=botocore.exceptions.ClientError(response, "HeadObject"))

    with mock.patch(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.aioboto3.Session"
    ) as mock_session_class:
        mock_session_class.return_value = _mock_s3_session_with_head_object(head_object)

        denied = await is_s3_read_access_denied(
            bucket="test-bucket",
            region_name="us-east-1",
            credentials=AWSCredentials(aws_access_key_id="key", aws_secret_access_key="secret"),
            keys=["some/manifest.json", "some/file-0.parquet.zst"],
        )

    assert denied is expected


async def test_is_s3_read_access_denied_swallows_unexpected_error():
    """An unexpected probe failure (e.g. a connection error) is treated as 'not confirmed' (False)."""
    head_object = mock.AsyncMock(side_effect=botocore.exceptions.EndpointConnectionError(endpoint_url="https://s3"))

    with mock.patch(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.aioboto3.Session"
    ) as mock_session_class:
        mock_session_class.return_value = _mock_s3_session_with_head_object(head_object)

        denied = await is_s3_read_access_denied(
            bucket="test-bucket",
            region_name="us-east-1",
            credentials=AWSCredentials(aws_access_key_id="key", aws_secret_access_key="secret"),
            keys=["some/manifest.json"],
        )

    assert denied is False


class _FakeDiag:
    def __init__(self, primary: str | None = None, detail: str | None = None):
        self.message_primary = primary
        self.message_detail = detail


class _FakeInternalError(psycopg.errors.InternalError_):
    """Stand-in for a Redshift COPY error. psycopg builds `diag` from driver state we can't fake, so
    we override it to expose the message fields the code inspects."""

    def __init__(self, message: str = "", *, primary: str | None = None, detail: str | None = None):
        super().__init__(message)
        self._fake_diag = _FakeDiag(primary, detail)

    @property
    def diag(self) -> Any:
        return self._fake_diag


@pytest.mark.parametrize("denied", [True, False])
async def test_check_and_raise_redshift_copy_error_credentials(denied):
    """With credential auth we probe S3 and only raise the specific error when read is denied."""
    credentials = AWSCredentials(aws_access_key_id="key", aws_secret_access_key="secret")

    with mock.patch(
        "products.batch_exports.backend.temporal.destinations.redshift_batch_export.is_s3_read_access_denied",
        new=mock.AsyncMock(return_value=denied),
    ):
        call = check_and_raise_redshift_copy_error(
            _FakeInternalError("COPY failed"),
            authorization=credentials,
            bucket="test-bucket",
            region_name="us-east-1",
            manifest_key="prefix/manifest.json",
            files_uploaded=["prefix/file-0.parquet.zst"],
        )
        if denied:
            with pytest.raises(InsufficientS3PermissionsError):
                await call
        else:
            await call  # should not raise


@pytest.mark.parametrize(
    "error,should_raise",
    [
        (_FakeInternalError("COPY with MANIFEST parameter requires full path of an S3 object"), True),
        (_FakeInternalError("copy failed", detail="S3ServiceException: Access Denied"), True),
        (_FakeInternalError("syntax error at or near 'foo'"), False),
    ],
)
async def test_check_and_raise_redshift_copy_error_iam_role(error, should_raise):
    """IAM role auth can't be probed, so we translate only recognised S3 read/access failures."""
    call = check_and_raise_redshift_copy_error(
        error,
        authorization="arn:aws:iam::123456789012:role/redshift-copy",
        bucket="test-bucket",
        region_name="us-east-1",
        manifest_key="prefix/manifest.json",
        files_uploaded=["prefix/file-0.parquet.zst"],
    )
    if should_raise:
        with pytest.raises(RedshiftS3CopyError):
            await call
    else:
        await call  # should not raise
