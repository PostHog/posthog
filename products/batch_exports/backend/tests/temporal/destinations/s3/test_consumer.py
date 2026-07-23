import pytest
from unittest import mock

import botocore.exceptions

from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    NON_RETRYABLE_ERROR_TYPES,
    ConcurrentS3Consumer,
    S3MultipartUploadNotFoundError,
)

pytestmark = [pytest.mark.asyncio]


def _make_consumer(s3_client) -> ConcurrentS3Consumer:
    return ConcurrentS3Consumer(
        s3_client=s3_client,
        bucket="test-bucket",
        region_name="us-east-1",
        prefix="test-prefix",
        data_interval_start="2023-04-25T13:30:00+00:00",
        data_interval_end="2023-04-25T14:30:00+00:00",
        batch_export_model=None,
        file_format="JSONLines",
    )


async def test_complete_multipart_upload_translates_no_such_upload():
    """A `NoSuchUpload` on completion (e.g. a bucket lifecycle rule aborted the upload) must
    surface as our non-retryable error, not a bare botocore `ClientError` that retries forever."""
    s3_client = mock.MagicMock()
    s3_client.complete_multipart_upload = mock.AsyncMock(
        side_effect=botocore.exceptions.ClientError(
            error_response={"Error": {"Code": "NoSuchUpload", "Message": "The specified upload does not exist."}},
            operation_name="CompleteMultipartUpload",
        )
    )

    consumer = _make_consumer(s3_client)
    consumer.upload_id = "gone-upload-id"

    with pytest.raises(S3MultipartUploadNotFoundError):
        await consumer._complete_multipart_upload()

    # The translated error must be registered as non-retryable, otherwise the activity retries anyway.
    assert S3MultipartUploadNotFoundError.__name__ in NON_RETRYABLE_ERROR_TYPES


async def test_complete_multipart_upload_reraises_other_client_errors():
    """Other client errors on completion stay as-is so their existing retry semantics are preserved."""
    s3_client = mock.MagicMock()
    s3_client.complete_multipart_upload = mock.AsyncMock(
        side_effect=botocore.exceptions.ClientError(
            error_response={"Error": {"Code": "InternalError", "Message": "We encountered an internal error."}},
            operation_name="CompleteMultipartUpload",
        )
    )

    consumer = _make_consumer(s3_client)
    consumer.upload_id = "some-upload-id"

    with pytest.raises(botocore.exceptions.ClientError):
        await consumer._complete_multipart_upload()
