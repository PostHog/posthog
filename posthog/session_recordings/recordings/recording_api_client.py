import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from django.conf import settings

import snappy
import aiohttp
import structlog

from posthog.session_recordings.recordings.errors import BlockFetchError, RecordingDeletedError

logger = structlog.get_logger(__name__)


class RecordingApiClient:
    """
    Async client for fetching recording blocks via the Recording API.

    The Recording API handles decryption transparently - encrypted sessions are
    decrypted using KMS, while unencrypted sessions pass through unchanged.
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
            raise BlockFetchError(f"Invalid range format: {parsed.query}")

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
                        "recording_api_client.recording_deleted",
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
                "recording_api_client.fetch_compressed_block_failed",
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
                "recording_api_client.fetch_block_failed",
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
                response.raise_for_status()
                return True
        except BlockFetchError:
            raise
        except aiohttp.ClientError as e:
            logger.exception(
                "recording_api_client.delete_recording_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to delete recording: {str(e)}")

    async def bulk_delete_recordings(self, session_ids: list[str], team_id: int) -> list[str]:
        """
        Bulk delete recordings via the Recording API.

        Returns list of session IDs that failed to delete.
        """
        url = f"{self.base_url}/api/projects/{team_id}/recordings/bulk_delete"

        try:
            async with self.session.post(url, json={"session_ids": session_ids}) as response:
                response.raise_for_status()
                data = await response.json()
                return [f["session_id"] for f in data.get("failed", [])]
        except aiohttp.ClientError as e:
            logger.exception(
                "recording_api_client.bulk_delete_failed",
                url=url,
                team_id=team_id,
                session_count=len(session_ids),
                error=str(e),
                exc_info=False,
            )
            return session_ids


@asynccontextmanager
async def recording_api_client() -> AsyncIterator[RecordingApiClient]:
    """
    Async context manager for creating a RecordingApiClient instance.

    Usage:
        async with recording_api_client() as client:
            content = await client.fetch_decompressed_block(block_url, session_id, team_id)
    """
    if not settings.RECORDING_API_URL:
        raise RuntimeError("RECORDING_API_URL is not configured")

    headers: dict[str, str] = {}
    if settings.INTERNAL_API_SECRET:
        headers["X-Internal-Api-Secret"] = settings.INTERNAL_API_SECRET
    elif not settings.DEBUG:
        logger.warning("recording_api_client.missing_internal_api_secret")

    timeout = aiohttp.ClientTimeout(total=30, connect=5)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        yield RecordingApiClient(session, settings.RECORDING_API_URL)
