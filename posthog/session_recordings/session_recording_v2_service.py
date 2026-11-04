import dataclasses

from django.core.cache import cache

import structlog
import posthoganalytics
from asgiref.sync import async_to_sync
from prometheus_client import Counter

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.recordings.errors import RecordingApiConfigurationError, RecordingDeletedError
from posthog.session_recordings.recordings.recording_api_client import recording_api_client

logger = structlog.get_logger(__name__)

BLOCK_LISTING_CACHE_HIT_COUNTER = Counter(
    "posthog_session_recording_v2_block_listing_cache_hit",
    "Number of times the block listing cache was hit",
    ["cache_hit"],
)


@dataclasses.dataclass(frozen=True)
class RecordingBlock:
    key: str
    start_byte: int
    end_byte: int
    start_timestamp: str
    end_timestamp: str
    # recording-api's opaque name for the block, which the player can fetch directly. None for a recording from
    # before encryption.
    ref: str | None = None


FIVE_SECONDS = 5


def listing_cache_key(recording: SessionRecording) -> str | None:
    try:
        # NB this has to be `team_id` and not `team.id` as it's called in an async context
        # and `team.id` can trigger a database query, and the Django ORM is synchronous
        return f"@posthog/v2-blob-snapshots/v2/recording_block_listing_{recording.team_id}_{recording.session_id}"
    except Exception as e:
        posthoganalytics.capture_exception(
            e,
            properties={
                "location": "session_recording_v2_service.listing_cache_key",
                "recording": recording.__dict__ if recording else None,
            },
        )
        return None


async def fetch_blocks_from_recording_api(session_id: str, team_id: int) -> list[RecordingBlock]:
    async with recording_api_client() as client:
        raw_blocks = await client.list_blocks(session_id, team_id)

    return [
        RecordingBlock(
            key=b["key"],
            start_byte=b["start_byte"],
            end_byte=b["end_byte"],
            start_timestamp=b["start_timestamp"],
            end_timestamp=b["end_timestamp"],
            ref=b.get("ref"),
        )
        for b in raw_blocks
    ]


def _get_cached_blocks(recording: SessionRecording) -> tuple[str | None, list[RecordingBlock] | None]:
    cache_key = listing_cache_key(recording)
    if cache_key is not None:
        cached_blocks = cache.get(cache_key)
        if cached_blocks is not None:
            BLOCK_LISTING_CACHE_HIT_COUNTER.labels(cache_hit=True).inc()
            return cache_key, cached_blocks
        else:
            BLOCK_LISTING_CACHE_HIT_COUNTER.labels(cache_hit=False).inc()
    return cache_key, None


def _cache_blocks(cache_key: str | None, blocks: list[RecordingBlock]) -> None:
    if blocks and cache_key is not None:
        cache.set(cache_key, blocks, timeout=FIVE_SECONDS)


def list_blocks(recording: SessionRecording, use_cache: bool = True) -> list[RecordingBlock]:
    """
    Returns a list of recording blocks fetched from the recording-api.
    Results are cached to avoid excessive calls.
    """
    return async_to_sync(list_blocks_async)(recording, use_cache=use_cache)


async def list_blocks_async(recording: SessionRecording, use_cache: bool = True) -> list[RecordingBlock]:
    """
    Async version of list_blocks, safe to call from within a running event loop.
    Pass use_cache=False where a deletion must show at once: the recording-api reports it, a cached listing does not.
    """
    cache_key, cached_blocks = _get_cached_blocks(recording) if use_cache else (listing_cache_key(recording), None)
    if cached_blocks is not None:
        return cached_blocks

    try:
        blocks = await fetch_blocks_from_recording_api(recording.session_id, recording.team_id)
    except (RecordingApiConfigurationError, RecordingDeletedError):
        # An empty listing is how a caller learns a recording has no blocks. A missing setting means no
        # call was made at all, and a deleted recording must say so before the player reaches cached blocks.
        raise
    except Exception:
        logger.exception(
            "recording_api_list_blocks_failed",
            session_id=recording.session_id,
            team_id=recording.team_id,
        )
        return []

    _cache_blocks(cache_key, blocks)
    return blocks
