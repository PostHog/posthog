from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from django.conf import settings

import aiohttp
import structlog
from prometheus_client import Counter
from tenacity import RetryCallState, retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from posthog.session_recordings.recordings.errors import (
    BlockFetchClientError,
    BlockFetchError,
    BlockNotFoundError,
    RecordingDeletedError,
    TransientBlockFetchError,
)

logger = structlog.get_logger(__name__)

# Counts the in-place block-fetch retries so the retry's effectiveness is measurable, not just its
# failures: "attempt" ticks once per retry (so a fetch that retries twice ticks it twice),
# "recovered" ticks at most once per fetch_block call, when a retried fetch finally succeeds. The
# two have different denominators (per-retry vs per-call) so their ratio is NOT a recovery rate;
# the give-up rate lives in BLOCK_FETCH_FAILURE_COUNTER{reason=transient}. Without this a rising
# upstream-flakiness trend is invisible until retries stop absorbing it.
BLOCK_FETCH_RETRY_COUNTER = Counter(
    "session_recording_block_fetch_retry_total",
    "Recording-api block fetch retries: outcome=attempt per retry, outcome=recovered per call that a retry rescued.",
    ["outcome"],
)

# 4xx statuses that are still worth retrying: the recording-api is asking us to back off
# (429 Too Many Requests) or the request timed out upstream (408 Request Timeout).
_RETRIABLE_4XX = {408, 429}

# How long we'll wait *inline* (sleeping a request worker) for a server-supplied Retry-After.
# Within this we honour it and retry in place; a 429 asking for longer is handed back to the
# client as a 429 + Retry-After (see fetch_block) so it can obey the back-off without pinning a
# worker. Aligned with the fallback backoff's own max so inline waits stay within a known bound.
_MAX_INLINE_RETRY_AFTER_SECONDS = 3.0

_fallback_wait = wait_random_exponential(multiplier=0.2, max=3)


def _retry_after_seconds(exc: BaseException) -> float | None:
    """The Retry-After (in seconds) on a ClientResponseError, or None if absent/unparseable."""
    if not isinstance(exc, aiohttp.ClientResponseError) or not exc.headers:
        return None
    retry_after = exc.headers.get("Retry-After")
    return _parse_retry_after(retry_after) if retry_after is not None else None


def _is_retriable_block_fetch(exc: BaseException) -> bool:
    """Whether a block fetch should be retried in-process.

    Recoverable: connection errors, timeouts, recording-api 5xx, and the back-off 4xx codes
    (408/429). Not recoverable: other 4xx responses (a genuine client error), the 404/410 cases
    (raised as BlockNotFoundError/RecordingDeletedError before reaching here), and a 429 whose
    Retry-After exceeds what we'll wait inline — that one is surfaced to the client instead.
    """
    if isinstance(exc, aiohttp.ClientResponseError):
        if exc.status < 500 and exc.status not in _RETRIABLE_4XX:
            return False
        if exc.status == 429:
            seconds = _retry_after_seconds(exc)
            if seconds is not None and seconds > _MAX_INLINE_RETRY_AFTER_SECONDS:
                return False
        return True
    return isinstance(exc, aiohttp.ClientError | TimeoutError)


def _parse_retry_after(value: str) -> float | None:
    """Parse a Retry-After header value (delta-seconds or HTTP-date) into seconds-from-now.

    Returns None when the value is empty or unparseable, so the caller falls back to its own
    backoff rather than trusting a malformed header.
    """
    value = value.strip()
    if not value:
        return None
    try:
        return float(int(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at is None:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return (retry_at - datetime.now(UTC)).total_seconds()


def _wait_block_fetch_retry(retry_state: RetryCallState) -> float:
    """Honour a recording-api Retry-After header when present, else exponential backoff.

    The header is the server explicitly telling us when to come back, so respecting it backs off
    a struggling upstream better than our own jittered guess. Only reached for retries we keep
    in-process, so the value is already within the inline budget; clamped to [0, budget] defensively.
    """
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    seconds = _retry_after_seconds(exc) if exc is not None else None
    if seconds is not None:
        return min(max(seconds, 0.0), _MAX_INLINE_RETRY_AFTER_SECONDS)
    return _fallback_wait(retry_state)


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

        retried = False

        def _count_retry(_retry_state: RetryCallState) -> None:
            nonlocal retried
            retried = True
            BLOCK_FETCH_RETRY_COUNTER.labels(outcome="attempt").inc()

        # Retry transient failures (connection errors, timeouts, recording-api 5xx) in place so a
        # single flaky block doesn't fail the whole snapshot request and force a full client retry.
        @retry(
            retry=retry_if_exception(_is_retriable_block_fetch),
            reraise=True,
            wait=_wait_block_fetch_retry,
            stop=stop_after_attempt(3),
            before_sleep=_count_retry,
        )
        async def _fetch() -> bytes:
            async with self.session.get(url, params=params) as response:
                if response.status == 404:
                    raise BlockNotFoundError("Block not found")
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

        try:
            content = await _fetch()
            if retried:
                # An earlier attempt failed transiently and a retry recovered it — count the
                # silent save so the retry's effectiveness shows up, not only its failures.
                BLOCK_FETCH_RETRY_COUNTER.labels(outcome="recovered").inc()
            return content
        except (RecordingDeletedError, BlockFetchError):
            raise
        except (aiohttp.ClientError, TimeoutError) as e:
            # A non-retriable client error (any 4xx we won't retry, including a 429 asking us to
            # back off longer than we'll wait inline): return the upstream status to the client
            # as-is rather than retrying or masking it as a transient 503.
            if isinstance(e, aiohttp.ClientResponseError) and not _is_retriable_block_fetch(e):
                raise BlockFetchClientError(
                    f"Recording API returned {e.status}",
                    status_code=e.status,
                    retry_after=e.headers.get("Retry-After") if e.headers else None,
                )
            logger.exception(
                "recording_api_client.fetch_block_failed",
                url=url,
                session_id=session_id,
                team_id=team_id,
                error=str(e),
                exc_info=False,
            )
            raise TransientBlockFetchError(f"Failed to fetch block from Recording API: {str(e)}")

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
