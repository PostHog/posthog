import abc
import structlog
from boto3 import client as boto3_client
from botocore.client import Config
from django.conf import settings
from urllib.parse import urlparse, parse_qs
import snappy
from typing import Optional

logger = structlog.get_logger(__name__)


class SessionRecordingV2ObjectStorageBase(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        pass

    @abc.abstractmethod
    def write(self, key: str, data: bytes) -> None:
        pass

    @abc.abstractmethod
    def is_enabled(self) -> bool:
        pass

    @abc.abstractmethod
    def fetch_block(self, block_url: str) -> tuple[Optional[str], Optional[str]]:
        """Returns a tuple of (decompressed_block, error_message)"""
        pass


class UnavailableSessionRecordingV2ObjectStorage(SessionRecordingV2ObjectStorageBase):
    def read_bytes(self, key: str, first_byte: int, last_byte: int) -> bytes | None:
        return None

    def write(self, key: str, data: bytes) -> None:
        pass

    def is_enabled(self) -> bool:
        return False

    def fetch_block(self, block_url: str) -> tuple[Optional[str], Optional[str]]:
        return None, "Storage not available"


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
                "session_recording_v2_object_storage.read_failed",
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

    def fetch_block(self, block_url: str) -> tuple[Optional[str], Optional[str]]:
        try:
            # Parse URL and extract key and byte range
            parsed_url = urlparse(block_url)
            key = parsed_url.path.lstrip("/")
            query_params = parse_qs(parsed_url.query)
            byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
            start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

            if start_byte is None or end_byte is None:
                return None, "Invalid byte range in block URL"

            expected_length = end_byte - start_byte + 1
            compressed_block = self.read_bytes(key, first_byte=start_byte, last_byte=end_byte)

            if not compressed_block:
                return None, "Block content not found"

            if len(compressed_block) != expected_length:
                return (
                    None,
                    f"Unexpected data length. Expected {expected_length} bytes, got {len(compressed_block)} bytes",
                )

            decompressed_block = snappy.decompress(compressed_block).decode("utf-8")
            # Ensure block ends with exactly one newline
            decompressed_block = decompressed_block.rstrip("\n") + "\n"
            return decompressed_block, None

        except Exception as e:
            logger.exception("Failed to read and decompress block", error=e)
            return None, f"Failed to read and decompress block: {str(e)}"


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
