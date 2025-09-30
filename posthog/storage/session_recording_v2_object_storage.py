import abc
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import parse_qs, urlparse

from django.conf import settings

import snappy
import structlog
import posthoganalytics
from aiobotocore.session import get_session
from boto3 import client as boto3_client
from botocore.client import Config

logger = structlog.get_logger(__name__)


class BlockDeleteError(Exception):
    pass


class BlockFetchError(Exception):
    pass


class FileFetchError(Exception):
    pass


class SessionRecordingV2ObjectStorageBase(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        pass

    @abc.abstractmethod
    def read_all_bytes(self, key: str) -> bytes | None:
        pass

    @abc.abstractmethod
    def write(self, key: str, data: bytes) -> None:
        pass

    @abc.abstractmethod
    def is_enabled(self) -> bool:
        pass

    @abc.abstractmethod
    def fetch_file(self, blob_key: str) -> str:
        """Returns the decompressed file or raises Error"""
        pass

    @abc.abstractmethod
    def fetch_block(self, block_url: str) -> str:
        """Returns the decompressed block or raises BlockFetchError"""
        pass

    @abc.abstractmethod
    def delete_block(self, block_url: str) -> None:
        """Zeroes out the specified block or raises BlockDeleteError"""
        pass

    @abc.abstractmethod
    def store_lts_recording(self, recording_id: str, recording_data: str) -> tuple[Optional[str], Optional[str]]:
        """Returns a tuple of (target_key, error_message)"""
        pass

    @abc.abstractmethod
    def is_lts_enabled(self) -> bool:
        pass


class UnavailableSessionRecordingV2ObjectStorage(SessionRecordingV2ObjectStorageBase):
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        return None

    def read_all_bytes(self, key: str) -> bytes | None:
        pass

    def write(self, key: str, data: bytes) -> None:
        pass

    def is_enabled(self) -> bool:
        return False

    def fetch_file(self, blob_key: str) -> str:
        raise FileFetchError("Storage not available")

    def fetch_block(self, block_url: str) -> str:
        raise BlockFetchError("Storage not available")

    def delete_block(self, block_url: str) -> None:
        raise BlockDeleteError("Storage not available")

    def store_lts_recording(self, recording_id: str, recording_data: str) -> tuple[Optional[str], Optional[str]]:
        return None, "Storage not available"

    def is_lts_enabled(self) -> bool:
        return False


class SessionRecordingV2ObjectStorage(SessionRecordingV2ObjectStorageBase):
    def __init__(self, aws_client, bucket: str) -> None:
        self.aws_client = aws_client
        self.bucket = bucket

    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        s3_response = {}
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
                "Range": f"bytes={first_byte}-{last_byte}",
            }
            s3_response = self.aws_client.get_object(**kwargs)
            return s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.read_bytes_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            return None

    def read_all_bytes(self, key: str) -> bytes | None:
        s3_response = {}
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
            }
            s3_response = self.aws_client.get_object(**kwargs)
            return s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.read_all_bytes_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            return None

    def write(self, key: str, data: bytes) -> None:
        s3_response = {}
        try:
            s3_response = self.aws_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
            )
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.write_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            raise Exception("Failed to write recording data") from e

    def is_enabled(self) -> bool:
        return True

    def fetch_file(self, blob_key: str) -> str:
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": blob_key,
            }
            s3_response = self.aws_client.get_object(**kwargs)
            file_body = s3_response["Body"].read()

            return snappy.decompress(file_body).decode("utf-8")

        except Exception as e:
            posthoganalytics.tag("bucket", self.bucket)
            logger.exception(
                "session_recording_v2_object_storage.fetch_file_failed",
                bucket=self.bucket,
                file_name=blob_key,
                error=e,
                s3_response=s3_response,
            )
            raise FileFetchError(f"Failed to read and decompress file: {str(e)}")

    def fetch_block(self, block_url: str) -> str:
        try:
            # Parse URL and extract key and byte range
            parsed_url = urlparse(block_url)
            key = parsed_url.path.lstrip("/")
            query_params = parse_qs(parsed_url.query)
            byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
            start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

            if start_byte is None or end_byte is None:
                raise BlockFetchError("Invalid byte range in block URL")

            expected_length = end_byte - start_byte + 1
            compressed_block = self.read_bytes(key, first_byte=start_byte, last_byte=end_byte)

            if not compressed_block:
                raise BlockFetchError("Block content not found")

            if len(compressed_block) != expected_length:
                raise BlockFetchError(
                    f"Unexpected data length. Expected {expected_length} bytes, got {len(compressed_block)} bytes"
                )

            decompressed_block = snappy.decompress(compressed_block).decode("utf-8")
            # Strip any trailing newlines
            decompressed_block = decompressed_block.rstrip("\n")
            return decompressed_block

        except BlockFetchError:
            raise
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.fetch_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
            )
            raise BlockFetchError(f"Failed to read and decompress block: {str(e)}")

    def delete_block(self, block_url: str) -> None:
        try:
            # Parse URL and extract key and byte range
            parsed_url = urlparse(block_url)
            key = parsed_url.path.lstrip("/")
            query_params = parse_qs(parsed_url.query)
            byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
            start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

            if start_byte is None or end_byte is None:
                raise BlockDeleteError("Invalid byte range in block URL")

            expected_length = end_byte - start_byte + 1

            file_bytes = self.read_all_bytes(key)

            if file_bytes is None:
                raise BlockDeleteError(f"Failed to read file {key}")

            new_file_bytes = bytes(
                bytearray(file_bytes[:start_byte]) + bytearray(expected_length) + bytearray(file_bytes[end_byte + 1 :])
            )

            self.write(key, new_file_bytes)
        except BlockDeleteError:
            raise
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.delete_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
            )
            raise BlockDeleteError(f"Failed to delete block: {str(e)}")

    def store_lts_recording(self, recording_id: str, recording_data: str) -> tuple[Optional[str], Optional[str]]:
        try:
            compressed_data = snappy.compress(recording_data.encode("utf-8"))
            base_key = f"{settings.SESSION_RECORDING_V2_S3_LTS_PREFIX}/{recording_id}"
            byte_range = f"bytes=0-{len(compressed_data) - 1}"
            target_key = f"s3://{self.bucket}/{base_key}?range={byte_range}"
            self.write(base_key, compressed_data)
            logger.info(
                "Successfully stored LTS recording",
                recording_id=recording_id,
                uncompressed_size=len(recording_data),
                compressed_size=len(compressed_data),
            )
            return target_key, None
        except Exception as e:
            logger.exception(
                "session_recording_v2_object_storage.store_lts_recording_failed",
                bucket=self.bucket,
                recording_id=recording_id,
                error=e,
            )
            return None, f"Failed to store LTS recording: {str(e)}"

    def is_lts_enabled(self) -> bool:
        return bool(settings.SESSION_RECORDING_V2_S3_LTS_PREFIX)


class AsyncSessionRecordingV2ObjectStorage:
    def __init__(self, aws_client, bucket: str) -> None:
        self.aws_client = aws_client
        self.bucket = bucket

    async def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        s3_response = {}
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
                "Range": f"bytes={first_byte}-{last_byte}",
            }
            s3_response = await self.aws_client.get_object(**kwargs)
            return await s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.read_bytes_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            return None

    async def read_all_bytes(self, key: str) -> bytes | None:
        s3_response = {}
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": key,
            }
            s3_response = await self.aws_client.get_object(**kwargs)
            return await s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.read_all_bytes_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            return None

    async def write(self, key: str, data: bytes) -> None:
        s3_response = {}
        try:
            s3_response = await self.aws_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
            )
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.write_failed",
                bucket=self.bucket,
                file_name=key,
                error=e,
                s3_response=s3_response,
            )
            raise Exception("Failed to write recording data") from e

    def is_enabled(self) -> bool:
        return True

    async def fetch_file(self, blob_key: str) -> str:
        try:
            kwargs = {
                "Bucket": self.bucket,
                "Key": blob_key,
            }
            s3_response = await self.aws_client.get_object(**kwargs)
            file_body = await s3_response["Body"].read()

            return snappy.decompress(file_body).decode("utf-8")
        except Exception as e:
            posthoganalytics.tag("bucket", self.bucket)
            logger.exception(
                "async_session_recording_v2_object_storage.fetch_file_failed",
                bucket=self.bucket,
                file_name=blob_key,
                error=e,
                s3_response=s3_response,
            )
            raise FileFetchError(f"Failed to read and decompress file: {str(e)}")

    async def fetch_block(self, block_url: str) -> str:
        try:
            # Parse URL and extract key and byte range
            parsed_url = urlparse(block_url)
            key = parsed_url.path.lstrip("/")
            query_params = parse_qs(parsed_url.query)
            byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
            start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

            if start_byte is None or end_byte is None:
                raise BlockFetchError("Invalid byte range in block URL")

            expected_length = end_byte - start_byte + 1
            compressed_block = await self.read_bytes(key, first_byte=start_byte, last_byte=end_byte)

            if not compressed_block:
                raise BlockFetchError("Block content not found")

            if len(compressed_block) != expected_length:
                raise BlockFetchError(
                    f"Unexpected data length. Expected {expected_length} bytes, got {len(compressed_block)} bytes"
                )

            decompressed_block = snappy.decompress(compressed_block).decode("utf-8")
            # Strip any trailing newlines
            decompressed_block = decompressed_block.rstrip("\n")
            return decompressed_block

        except BlockFetchError:
            raise
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.fetch_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
            )
            raise BlockFetchError(f"Failed to read and decompress block: {str(e)}")

    async def delete_block(self, block_url: str) -> None:
        try:
            # Parse URL and extract key and byte range
            parsed_url = urlparse(block_url)
            key = parsed_url.path.lstrip("/")
            query_params = parse_qs(parsed_url.query)
            byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
            start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

            if start_byte is None or end_byte is None:
                raise BlockDeleteError("Invalid byte range in block URL")

            expected_length = end_byte - start_byte + 1

            file_bytes = await self.read_all_bytes(key)

            if file_bytes is None:
                raise BlockDeleteError(f"Failed to read file {key}")

            new_file_bytes = bytes(
                bytearray(file_bytes[:start_byte]) + bytearray(expected_length) + bytearray(file_bytes[end_byte + 1 :])
            )

            await self.write(key, new_file_bytes)
        except BlockDeleteError:
            raise
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.delete_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
            )
            raise BlockDeleteError(f"Failed to delete block: {str(e)}")

    async def store_lts_recording(self, recording_id: str, recording_data: str) -> tuple[Optional[str], Optional[str]]:
        try:
            compressed_data = snappy.compress(recording_data.encode("utf-8"))
            base_key = f"{settings.SESSION_RECORDING_V2_S3_LTS_PREFIX}/{recording_id}"
            byte_range = f"bytes=0-{len(compressed_data) - 1}"
            target_key = f"s3://{self.bucket}/{base_key}?range={byte_range}"
            await self.write(base_key, compressed_data)
            logger.info(
                "Successfully stored LTS recording",
                recording_id=recording_id,
                uncompressed_size=len(recording_data),
                compressed_size=len(compressed_data),
            )
            return target_key, None
        except Exception as e:
            logger.exception(
                "async_session_recording_v2_object_storage.store_lts_recording_failed",
                bucket=self.bucket,
                recording_id=recording_id,
                error=e,
            )
            return None, f"Failed to store LTS recording: {str(e)}"

    def is_lts_enabled(self) -> bool:
        return bool(settings.SESSION_RECORDING_V2_S3_LTS_PREFIX)


_client: SessionRecordingV2ObjectStorageBase = UnavailableSessionRecordingV2ObjectStorage()


def client() -> SessionRecordingV2ObjectStorageBase:
    global _client

    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        _client = UnavailableSessionRecordingV2ObjectStorage()
    elif isinstance(_client, UnavailableSessionRecordingV2ObjectStorage):
        _client = SessionRecordingV2ObjectStorage(
            boto3_client(
                "s3",
                endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
                aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
                aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
                config=Config(
                    signature_version="s3v4",
                    connect_timeout=1,
                    retries={"max_attempts": 1},
                ),
                region_name=settings.SESSION_RECORDING_V2_S3_REGION,
            ),
            bucket=settings.SESSION_RECORDING_V2_S3_BUCKET,
        )

    return _client


@asynccontextmanager
async def async_client() -> AsyncIterator[AsyncSessionRecordingV2ObjectStorage]:
    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        raise RuntimeError("Missing required settings for object storage client")
    else:
        session = get_session()
        async with session.create_client(  # type: ignore[call-overload]
            "s3",
            endpoint_url=settings.SESSION_RECORDING_V2_S3_ENDPOINT,
            aws_access_key_id=settings.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                connect_timeout=1,
                retries={"max_attempts": 1},
            ),
            region_name=settings.SESSION_RECORDING_V2_S3_REGION,
        ) as client:
            yield AsyncSessionRecordingV2ObjectStorage(
                client,
                bucket=settings.SESSION_RECORDING_V2_S3_BUCKET,
            )
