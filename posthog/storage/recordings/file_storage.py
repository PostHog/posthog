from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.conf import settings

import snappy
import aioboto3
import structlog
from boto3 import client as boto3_client
from botocore.client import Config

from posthog.storage.recordings.errors import FileFetchError, FileUploadError

logger = structlog.get_logger(__name__)


class FileStorage:
    def __init__(self, client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    def upload_file(self, key: str, filename: str) -> None:
        """Upload a file to S3."""
        try:
            self._client.upload_file(
                Filename=filename,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception as e:
            logger.exception(
                "file_storage.upload_file_failed",
                bucket=self._bucket,
                key=key,
                filename=filename,
                error=e,
                exc_info=False,
            )
            raise FileUploadError(f"Failed to upload file: {str(e)}") from e

    def download_file(self, key: str) -> bytes:
        """Download a file from S3."""
        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=key,
            )
            return response["Body"].read()
        except Exception as e:
            logger.exception(
                "file_storage.download_file_failed",
                bucket=self._bucket,
                key=key,
                error=e,
                exc_info=False,
            )
            raise FileFetchError(f"Failed to download file: {str(e)}") from e

    def download_file_decompressed(self, key: str) -> str:
        """Download and decompress a file from S3."""
        try:
            compressed = self.download_file(key)
            return snappy.decompress(compressed).decode("utf-8")
        except FileFetchError:
            raise
        except Exception as e:
            logger.exception(
                "file_storage.download_file_decompressed_failed",
                bucket=self._bucket,
                key=key,
                error=e,
                exc_info=False,
            )
            raise FileFetchError(f"Failed to decompress file: {str(e)}") from e


class AsyncFileStorage:
    def __init__(self, client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def upload_file(self, key: str, filename: str) -> None:
        """Upload a file to S3."""
        try:
            await self._client.upload_file(
                Filename=filename,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception as e:
            logger.exception(
                "async_file_storage.upload_file_failed",
                bucket=self._bucket,
                key=key,
                filename=filename,
                error=e,
                exc_info=False,
            )
            raise FileUploadError(f"Failed to upload file: {str(e)}") from e

    async def download_file(self, key: str) -> bytes:
        """Download a file from S3."""
        try:
            response = await self._client.get_object(
                Bucket=self._bucket,
                Key=key,
            )
            return await response["Body"].read()
        except Exception as e:
            logger.exception(
                "async_file_storage.download_file_failed",
                bucket=self._bucket,
                key=key,
                error=e,
                exc_info=False,
            )
            raise FileFetchError(f"Failed to download file: {str(e)}") from e

    async def download_file_decompressed(self, key: str) -> str:
        """Download and decompress a file from S3."""
        try:
            compressed = await self.download_file(key)
            return snappy.decompress(compressed).decode("utf-8")
        except FileFetchError:
            raise
        except Exception as e:
            logger.exception(
                "async_file_storage.download_file_decompressed_failed",
                bucket=self._bucket,
                key=key,
                error=e,
                exc_info=False,
            )
            raise FileFetchError(f"Failed to decompress file: {str(e)}") from e


def file_storage() -> FileStorage:
    """Create a sync FileStorage client."""
    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        raise RuntimeError("Missing required settings for file storage client")

    s3_client = boto3_client(
        "s3",
        endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.SESSION_RECORDING_V2_S3_REGION,
    )
    return FileStorage(s3_client, bucket=settings.SESSION_RECORDING_V2_S3_BUCKET)


@asynccontextmanager
async def async_file_storage() -> AsyncIterator[AsyncFileStorage]:
    """Create an async FileStorage client."""
    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        raise RuntimeError("Missing required settings for file storage client")

    session = aioboto3.Session()
    async with session.client(  # type: ignore[call-overload]
        "s3",
        endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.SESSION_RECORDING_V2_S3_REGION,
    ) as s3_client:
        yield AsyncFileStorage(s3_client, bucket=settings.SESSION_RECORDING_V2_S3_BUCKET)
