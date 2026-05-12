from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from django.conf import settings

import aiohttp
import structlog

from posthog.session_recordings.recordings.errors import BlockFetchError, RecordingDeletedError

logger = structlog.get_logger(__name__)


# WORKAROUND for an ultimate-express bug in the recording-api Express server.
# In ultimate-express 2.0.9 (the version PostHog's pnpm-lock pins), routes mounted
# via `app.use('/', router())` — which is how every `/api/projects/.../recordings/...`
# route in `recording-api.ts` is registered — silently 404 with the default Express
# "Cannot GET ..." HTML page for ~50% of newly-opened TCP connections. Once a
# connection enters that state it never recovers; once it doesn't, every request
# on the same connection succeeds. Side-channel routes like `/_health` (mounted
# directly via `app.get`) are unaffected.
#
# The Django-side flow (this file) opens a fresh aiohttp.ClientSession per call —
# each session uses a fresh TCP connection. With a 50% bad-connection rate per
# session, a single `_fetch_blocks_parallel` (which fires N parallel block fetches)
# succeeds only ~(1/2)^N of the time, which is why self-hosted users have reported
# session replays hanging on the buffering spinner.
#
# This workaround probes each freshly-opened session against a router-mounted
# endpoint and treats an HTML response as a poisoned connection — closing the
# session and trying again with a fresh TCP. With a per-attempt 50% miss rate
# and 6 attempts, the probability of yielding a poisoned session drops to ~1.6%.
# Once a non-HTML response confirms the session is healthy, `limit_per_host=1`
# keeps every subsequent request pinned to that known-good connection.
#
# Defaults to enabled. Set `RECORDING_API_PROBE_ON_OPEN = False` in settings if
# your deployment uses a recording-api build with a fixed ultimate-express (e.g.
# >= 2.0.10) or a different HTTP server.
_PROBE_SESSION_ID = "00000000-0000-0000-0000-000000000000"
_PROBE_TEAM_ID = 1
_MAX_PROBES = 6


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


def _build_session(
    timeout: aiohttp.ClientTimeout, headers: dict[str, str], limit_per_host: int
) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(limit_per_host=limit_per_host)
    # nosemgrep: aiohttp-missing-trust-env -- internal service call to recording API
    return aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=False, connector=connector)


async def _probe_for_good_session(
    base_url: str, timeout: aiohttp.ClientTimeout, headers: dict[str, str]
) -> aiohttp.ClientSession:
    """Open sessions until one yields a non-HTML response to the probe URL.

    See module docstring for the ultimate-express bug this exists to avoid.
    Returns the last attempted session if all probes get a poisoned TCP, so the
    caller still gets a usable (if buggy) client — subsequent calls will surface
    the underlying issue through normal aiohttp errors rather than hanging here.
    """
    probe_url = f"{base_url.rstrip('/')}/api/projects/{_PROBE_TEAM_ID}/recordings/{_PROBE_SESSION_ID}/blocks"
    # _MAX_PROBES is guaranteed >= 1, so last_session is always assigned in the loop;
    # the type stays Optional here to keep `if last_session is not None: close()` safe
    # for the first iteration.
    last_session: aiohttp.ClientSession | None = None
    last_error: BaseException | None = None
    saw_html = False
    for _attempt in range(_MAX_PROBES):
        if last_session is not None:
            await last_session.close()
        last_session = _build_session(timeout, headers, limit_per_host=1)
        try:
            async with last_session.get(probe_url) as resp:
                ct = (resp.headers.get("content-type") or "").lower()
                if "text/html" not in ct:
                    return last_session
                saw_html = True
        except aiohttp.ClientError as e:
            last_error = e
    if saw_html and last_error is None:
        # All responses came back, just as HTML — the ultimate-express bug.
        hint = (
            "recording-api is returning HTML for router-mounted routes — "
            "this usually points at the ultimate-express route-miss bug (see module docstring)"
        )
    elif last_error is not None and not saw_html:
        # All probes failed to even connect. Probably a different problem entirely.
        hint = "recording-api connection failures on every probe attempt — server may be down or unreachable"
    else:
        # Mixed signals — both ClientError and HTML 404s. Surface both.
        hint = (
            "recording-api probes failed with a mix of connection errors and HTML route-miss responses — "
            "check server health AND see module docstring for the ultimate-express bug"
        )
    logger.warning(
        "recording_api_client.probe_exhausted",
        attempts=_MAX_PROBES,
        last_error=str(last_error) if last_error is not None else None,
        saw_html=saw_html,
        hint=hint,
    )
    # _MAX_PROBES >= 1 so `last_session` was assigned at least once above.
    return cast(aiohttp.ClientSession, last_session)


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
    if getattr(settings, "RECORDING_API_PROBE_ON_OPEN", True):
        session = await _probe_for_good_session(settings.RECORDING_API_URL, timeout, headers)
    else:
        # nosemgrep: aiohttp-missing-trust-env -- internal service call to recording API
        session = aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=False)
    try:
        yield RecordingApiClient(session, settings.RECORDING_API_URL)
    finally:
        await session.close()
