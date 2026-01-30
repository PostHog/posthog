import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

from django.conf import settings

import snappy
import aiohttp
import aioboto3
import structlog
from botocore.client import Config

from posthog.storage.recordings.errors import BlockFetchError, RecordingDeletedError

logger = structlog.get_logger(__name__)


@runtime_checkable
class BlockStorage(Protocol):
    """
    Protocol for fetching recording blocks.

    Both the S3 storage client and the Recording API client implement this interface,
    allowing them to be used interchangeably when fetching blocks.

    The session_id and team_id parameters are required for the Recording API client
    to construct the correct URL, but are ignored by the S3 storage client.
    """

    async def fetch_decompressed_block(self, block_url: str, session_id: str, team_id: int) -> str:
        """Fetch and decompress a recording block. Returns decompressed content."""
        ...

    async def fetch_compressed_block(self, block_url: str, session_id: str, team_id: int) -> bytes:
        """Fetch a recording block. Returns compressed bytes."""
        ...


class ClearTextBlockStorage:
    def __init__(self, aws_client, bucket: str) -> None:
        self.aws_client = aws_client
        self.bucket = bucket

    async def _fetch_compressed_block(self, block_url: str) -> bytes:
        """Internal method to fetch and validate compressed block"""
        parsed_url = urlparse(block_url)
        key = parsed_url.path.lstrip("/")
        query_params = parse_qs(parsed_url.query)
        byte_range = query_params.get("range", [""])[0].replace("bytes=", "")
        start_byte, end_byte = map(int, byte_range.split("-")) if "-" in byte_range else (None, None)

        if start_byte is None or end_byte is None:
            raise BlockFetchError("Invalid byte range in block URL")

        expected_length = end_byte - start_byte + 1

        try:
            s3_response = await self.aws_client.get_object(
                Bucket=self.bucket,
                Key=key,
                Range=f"bytes={start_byte}-{end_byte}",
            )
            compressed_block = await s3_response["Body"].read()
        except Exception as e:
            logger.exception(
                "async_recording_block_storage.fetch_compressed_block_failed",
                bucket=self.bucket,
                key=key,
                error=e,
                exc_info=False,
            )
            raise BlockFetchError("Block content not found") from e

        if not compressed_block:
            raise BlockFetchError("Block content not found")

        if len(compressed_block) != expected_length:
            raise BlockFetchError(
                f"Unexpected data length. Expected {expected_length} bytes, got {len(compressed_block)} bytes"
            )

        return compressed_block

    async def fetch_decompressed_block(
        self, block_url: str, session_id: str | None = None, team_id: int | None = None
    ) -> str:
        # session_id and team_id are accepted for interface compatibility but not used for S3 storage
        try:
            compressed_block = await self._fetch_compressed_block(block_url)
            decompressed_block = snappy.decompress(compressed_block).decode("utf-8")
            # Strip any trailing newlines
            decompressed_block = decompressed_block.rstrip("\n")
            return decompressed_block

        except BlockFetchError:
            raise
        except Exception as e:
            logger.exception(
                "async_recording_block_storage.fetch_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to read and decompress block: {str(e)}")

    async def fetch_compressed_block(
        self, block_url: str, session_id: str | None = None, team_id: int | None = None
    ) -> bytes:
        # session_id and team_id are accepted for interface compatibility but not used for S3 storage
        try:
            return await self._fetch_compressed_block(block_url)
        except BlockFetchError:
            raise
        except Exception as e:
            logger.exception(
                "async_recording_block_storage.fetch_compressed_block_failed",
                bucket=self.bucket,
                block_url=block_url,
                error=e,
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to read compressed block: {str(e)}")


@asynccontextmanager
async def cleartext_block_storage() -> AsyncIterator[ClearTextBlockStorage]:
    required_settings = [
        settings.SESSION_RECORDING_V2_S3_ENDPOINT,
        settings.SESSION_RECORDING_V2_S3_REGION,
        settings.SESSION_RECORDING_V2_S3_BUCKET,
    ]

    if not all(required_settings):
        raise RuntimeError("Missing required settings for object storage client")
    else:
        session = aioboto3.Session()
        async with session.client(  # type: ignore[call-overload]
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
            yield ClearTextBlockStorage(
                client,
                bucket=settings.SESSION_RECORDING_V2_S3_BUCKET,
            )


class EncryptedBlockStorage:
    """
    Async client for fetching recording blocks via the Recording API.

    The Recording API handles decryption transparently - encrypted sessions are
    decrypted using KMS, while unencrypted sessions pass through unchanged.
    This allows gradual migration from direct S3 reads to API-based reads.
    """

    def __init__(self, session: aiohttp.ClientSession, base_url: str):
        self.session = session
        self.base_url = base_url.rstrip("/")

    def _parse_block_url(self, block_url: str) -> tuple[str, int, int]:
        """
        Parse a block URL to extract the key, start byte, and end byte.

        The block_url is in the format: s3://bucket/key?range=bytes=start-end
        Returns a tuple of (key, start, end).
        """
        parsed = urlparse(block_url)
        key = parsed.path.lstrip("/")

        match = re.match(r"^range=bytes=(\d+)-(\d+)$", parsed.query)
        if not match:
            raise ValueError(f"Invalid range format: {parsed.query}")

        return key, int(match.group(1)), int(match.group(2))

    async def fetch_compressed_block(self, block_url: str, session_id: str, team_id: int) -> bytes:
        """
        Fetch a recording block via the Recording API.

        Returns the decrypted but still snappy-compressed block bytes.

        Raises:
            RecordingDeletedError: If the recording has been deleted.
            BlockFetchError: If the block is not found or other fetch errors occur.
        """
        key, start, end = self._parse_block_url(block_url)
        url = f"{self.base_url}/api/projects/{team_id}/recordings/{session_id}/block"

        try:
            async with self.session.get(url, params={"key": key, "start": start, "end": end}) as response:
                if response.status == 404:
                    raise BlockFetchError("Block not found")
                if response.status == 410:
                    data = await response.json()
                    deleted_at = data.get("deleted_at")
                    logger.info(
                        "encrypted_block_storage.recording_deleted",
                        session_id=session_id,
                        team_id=team_id,
                        deleted_at=deleted_at,
                    )
                    raise RecordingDeletedError("Recording has been deleted", deleted_at=deleted_at)
                response.raise_for_status()
                return await response.read()
        except (RecordingDeletedError, BlockFetchError):
            raise
        except aiohttp.ClientError as e:
            logger.exception(
                "encrypted_block_storage.fetch_compressed_block_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to fetch block from Recording API: {str(e)}")

    async def fetch_decompressed_block(self, block_url: str, session_id: str, team_id: int) -> str:
        """
        Fetch and decompress a recording block via the Recording API.

        Returns the decrypted and decompressed block content as a string.

        Raises:
            RecordingDeletedError: If the recording has been deleted.
            BlockFetchError: If the block is not found or other fetch errors occur.
        """
        try:
            compressed_block = await self.fetch_compressed_block(block_url, session_id, team_id)
            decompressed_block = snappy.decompress(compressed_block).decode("utf-8")
            return decompressed_block.rstrip("\n")
        except (RecordingDeletedError, BlockFetchError):
            raise
        except Exception as e:
            logger.exception(
                "encrypted_block_storage.fetch_block_failed",
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to decompress block: {str(e)}")

    async def delete_recording(self, session_id: str, team_id: int) -> bool:
        """
        Delete a recording's encryption key via the Recording API.

        Returns True if the key was deleted.

        Raises:
            RecordingDeletedError: If the recording has already been deleted.
            BlockFetchError: If the recording key is not found or other errors occur.
        """
        url = f"{self.base_url}/api/projects/{team_id}/recordings/{session_id}"

        try:
            async with self.session.delete(url) as response:
                if response.status == 404:
                    raise BlockFetchError("Recording key not found")
                if response.status == 410:
                    data = await response.json()
                    deleted_at = data.get("deleted_at")
                    logger.info(
                        "encrypted_block_storage.recording_already_deleted",
                        session_id=session_id,
                        team_id=team_id,
                        deleted_at=deleted_at,
                    )
                    raise RecordingDeletedError("Recording has already been deleted", deleted_at=deleted_at)
                response.raise_for_status()
                return True
        except (RecordingDeletedError, BlockFetchError):
            raise
        except aiohttp.ClientError as e:
            logger.exception(
                "encrypted_block_storage.delete_recording_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to delete recording: {str(e)}")


@asynccontextmanager
async def encrypted_block_storage() -> AsyncIterator[EncryptedBlockStorage]:
    """
    Async context manager for creating a EncryptedBlockStorage.

    Usage:
        async with encrypted_block_storage() as storage:
            content = await storage.fetch_decompressed_block(block_url, session_id, team_id)
    """
    if not settings.RECORDING_API_URL:
        raise RuntimeError("RECORDING_API_URL is not configured")

    timeout = aiohttp.ClientTimeout(total=30, connect=5)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        yield EncryptedBlockStorage(session, settings.RECORDING_API_URL)
