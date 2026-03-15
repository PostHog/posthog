from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.conf import settings

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

    async def fetch_block(
        self, key: str, start_byte: int, end_byte: int, session_id: str, team_id: int, *, decompress: bool = False
    ) -> bytes:
        url = f"{self.base_url}/api/projects/{team_id}/recordings/{session_id}/block"
        params: dict[str, str | int] = {"key": key, "start_byte": start_byte, "end_byte": end_byte}
        if decompress:
            params["decompress"] = "true"

        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 404:
                    raise BlockFetchError("Block not found")
                if response.status == 410:
                    data = await response.json()
                    deleted_at = data.get("deleted_at")
                    deleted_by = data.get("deleted_by")
                    logger.info(
                        "recording_api_client.recording_deleted",
                        session_id=session_id,
                        team_id=team_id,
                        deleted_at=deleted_at,
                        deleted_by=deleted_by,
                    )
                    raise RecordingDeletedError(
                        "Recording has been deleted", deleted_at=deleted_at, deleted_by=deleted_by
                    )
                response.raise_for_status()
                return await response.read()
        except (RecordingDeletedError, BlockFetchError):
            raise
        except aiohttp.ClientError as e:
            logger.exception(
                "recording_api_client.fetch_block_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise BlockFetchError(f"Failed to fetch block from Recording API: {str(e)}")

    async def list_blocks(self, session_id: str, team_id: int) -> list[dict]:
        url = f"{self.base_url}/api/projects/{team_id}/recordings/{session_id}/blocks"

        try:
            async with self.session.get(url) as response:
                if response.status == 404:
                    return []
                response.raise_for_status()
                data = await response.json()
            return data.get("blocks", [])
        except aiohttp.ClientError as e:
            logger.exception(
                "recording_api_client.list_blocks_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise

    async def delete_recordings(self, session_ids: list[str], team_id: int, deleted_by: str) -> list[str]:
        """
        Delete recordings via the Recording API.

        Returns list of session IDs that failed to delete.
        """
        url = f"{self.base_url}/api/projects/{team_id}/recordings/delete"

        try:
            async with self.session.post(url, json={"session_ids": session_ids, "deleted_by": deleted_by}) as response:
                response.raise_for_status()
                data = await response.json()
                return [r["sessionId"] for r in data if not r.get("ok")]
        except aiohttp.ClientError as e:
            logger.exception(
                "recording_api_client.delete_recordings_failed",
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
            content = await client.fetch_block(key, start, end, session_id, team_id, decompress=True)
    """
    if not settings.RECORDING_API_URL:
        raise RuntimeError("RECORDING_API_URL is not configured")

    headers: dict[str, str] = {}
    if settings.INTERNAL_API_SECRET:
        headers["X-Internal-Api-Secret"] = settings.INTERNAL_API_SECRET
    elif not settings.DEBUG:
        logger.warning("recording_api_client.missing_internal_api_secret")

    timeout = aiohttp.ClientTimeout(total=30, connect=5)
    # nosemgrep: aiohttp-missing-trust-env -- internal service call to recording API
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=False) as session:
        yield RecordingApiClient(session, settings.RECORDING_API_URL)
