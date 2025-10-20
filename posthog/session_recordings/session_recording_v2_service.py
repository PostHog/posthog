import dataclasses
from datetime import datetime

from django.core.cache import cache

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.session_recordings.models.metadata import RecordingBlockListing
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.storage import session_recording_v2_object_storage
from posthog.storage.session_recording_v2_object_storage import BlockFetchError

logger = structlog.get_logger(__name__)

BLOCK_URL_CACHE_HIT_COUNTER = Counter(
    "posthog_session_recording_v2_block_url_cache_hit", "Number of times the block URL cache was hit", ["cache_hit"]
)


@dataclasses.dataclass(frozen=True)
class RecordingBlock:
    start_time: datetime
    end_time: datetime
    url: str


FIVE_SECONDS = 5
ONE_DAY_IN_SECONDS = 24 * 60 * 60


def listing_cache_key(recording: SessionRecording) -> str | None:
    try:
        # NB this has to be `team_id` and not `team.id` as it's called in an async context
        # and `team.id` can trigger a database query, and the Django ORM is synchronous
        return f"@posthog/v2-blob-snapshots/v1/recording_block_listing_{recording.team_id}_{recording.session_id}"
    except Exception as e:
        posthoganalytics.capture_exception(
            e,
            properties={
                "location": "session_recording_v2_service.listing_cache_key",
                "recording": recording.__dict__ if recording else None,
            },
        )
        return None


def within_the_last_day(start_time: datetime | None) -> bool:
    if start_time is None:
        return False

    return (datetime.now(start_time.tzinfo) - start_time).total_seconds() < ONE_DAY_IN_SECONDS


def load_blocks(recording: SessionRecording) -> RecordingBlockListing | None:
    """
    When API clients are requesting v2 recordings, there is a dependency on querying ClickHouse for the metadata
    We can have a cache of differing length depending on the age of the recording.
    So that when a client ignores cache headers, or if they are paging through all blocks,
    then we don't hit ClickHouse too often.
    """
    cache_key = listing_cache_key(recording)
    if cache_key is not None:
        cached_block_listing = cache.get(cache_key)
        if cached_block_listing is not None:
            BLOCK_URL_CACHE_HIT_COUNTER.labels(cache_hit=True).inc()
            return cached_block_listing
        else:
            BLOCK_URL_CACHE_HIT_COUNTER.labels(cache_hit=False).inc()

    listed_blocks = SessionReplayEvents().list_blocks(
        recording.session_id, recording.team, recording_start_time=recording.start_time, ttl_days=recording.ttl_days
    )

    if listed_blocks is not None and not listed_blocks.is_empty() and cache_key is not None:
        # If a recording started more than 24 hours ago, then it is complete
        # we can cache it for a long time.
        # If not, we might still be receiving blocks, so we cache it for a short time.
        # Blob ingestion flushes frequently, so we want not too short a cache.
        # But without a cache we read from clickhouse too often
        timeout = FIVE_SECONDS if within_the_last_day(recording.start_time) else ONE_DAY_IN_SECONDS
        logger.info(
            "caching recording blocks",
            cache_key=cache_key,
            timeout=timeout,
            start_time=recording.start_time,
            is_within_the_last_day=within_the_last_day(recording.start_time),
            now=datetime.now(),
            number_of_blocks=len(listed_blocks.block_urls) if listed_blocks else 0,
            team_id=recording.team_id,
            session_id=recording.session_id,
        )
        # KLUDGE: i want to be able to cache for longer but believe i'm seeing incorrect caching behaviour
        # so i'm setting it to alway be 5 seconds for now, and adding a log to see if the 24 hour cache is incorrect
        cache.set(cache_key, listed_blocks, timeout=FIVE_SECONDS)

    return listed_blocks


def list_blocks(recording: SessionRecording) -> list[RecordingBlock]:
    """
    Returns a list of recording blocks with their timestamps and URLs.
    The blocks are sorted by start time and guaranteed to start from the beginning of the recording.
    Returns an empty list if the recording is invalid or incomplete.
    """
    recording_blocks = load_blocks(recording)
    return build_block_list(recording.session_id, recording.team.id, recording_blocks)


def build_block_list(
    session_id: str, team_id: int, recording_blocks: RecordingBlockListing | None
) -> list[RecordingBlock]:
    if not recording_blocks:
        return []

    first_timestamps = recording_blocks.block_first_timestamps
    last_timestamps = recording_blocks.block_last_timestamps
    urls = recording_blocks.block_urls

    # Validate that all arrays exist and have the same length
    if not (
        first_timestamps and last_timestamps and urls and len(first_timestamps) == len(last_timestamps) == len(urls)
    ):
        logger.error(
            "session recording metadata arrays length mismatch",
            session_id=session_id,
            team_id=team_id,
            first_timestamps_length=len(first_timestamps) if first_timestamps else 0,
            last_timestamps_length=len(last_timestamps) if last_timestamps else 0,
            urls_length=len(urls) if urls else 0,
        )
        return []

    blocks: list[RecordingBlock] = [
        RecordingBlock(
            start_time=start_time,
            end_time=end_time,
            url=url,
        )
        for start_time, end_time, url in zip(first_timestamps, last_timestamps, urls)
    ]

    blocks.sort(key=lambda b: b.start_time)

    # If we started recording halfway through the session, we should not return any blocks
    # as we don't have the complete recording from the start
    if not blocks or not recording_blocks.start_time or blocks[0].start_time != recording_blocks.start_time:
        return []

    return blocks


def copy_to_lts(recording: SessionRecording) -> str | None:
    """
    Copy a session recording's blocks to LTS (Long Term Storage).

    Returns the LTS path if successful, None if failed.
    Raises BlockFetchError if unable to fetch blocks.
    """
    storage_client = session_recording_v2_object_storage.client()
    if not storage_client.is_enabled() or not storage_client.is_lts_enabled():
        logger.info(
            "LTS storage not enabled, skipping copy",
            session_id=recording.session_id,
            team_id=recording.team_id,
        )
        return None

    blocks = list_blocks(recording)
    if not blocks:
        logger.info(
            "No v2 metadata found for recording or recording is incomplete, skipping copy to LTS",
            session_id=recording.session_id,
            team_id=recording.team_id,
        )
        return None

    decompressed_blocks = []
    for block in blocks:
        try:
            decompressed_block = storage_client.fetch_block(block.url)
            decompressed_blocks.append(decompressed_block)
        except BlockFetchError:
            logger.exception(
                "Failed to fetch block during LTS copy",
                session_id=recording.session_id,
                team_id=recording.team_id,
                block_url=block.url,
            )
            raise

    full_recording_data = "\n".join(decompressed_blocks)
    target_key, error = storage_client.store_lts_recording(recording.session_id, full_recording_data)

    if error:
        logger.error(
            "Failed to store recording in LTS",
            session_id=recording.session_id,
            team_id=recording.team_id,
            error=error,
        )
        return None

    return target_key
