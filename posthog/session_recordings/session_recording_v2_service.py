import dataclasses
from datetime import datetime
import structlog
from django.core.cache import cache
from posthog.session_recordings.models.metadata import RecordingBlockListing
from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class RecordingBlock:
    start_time: datetime
    end_time: datetime
    url: str


FIVE_SECONDS = 5
ONE_DAY_IN_SECONDS = 24 * 60 * 60


def listing_cache_key(recording: SessionRecording) -> str:
    return f"@posthog/v2-blob-snapshots/recording_block_listing_{recording.team.id}_{recording.session_id}"


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
    cached_block_listing = cache.get(cache_key)
    if (
        cached_block_listing is not None
        and isinstance(cached_block_listing, RecordingBlockListing)
        and not cached_block_listing.is_empty()
    ):
        return cached_block_listing

    listed_blocks = SessionReplayEvents().list_blocks(recording.session_id, recording.team)

    if listed_blocks is not None and not listed_blocks.is_empty():
        # If a recording started more than 24 hours ago, then it is complete
        # we can cache it for a long time.
        # If not, we might still be receiving blocks, so we cache it for a short time.
        # Blob ingestion flushes frequently, so we want not too short a cache.
        # But without a cache we read from clickhouse too often
        timeout = FIVE_SECONDS if within_the_last_day(recording.start_time) else ONE_DAY_IN_SECONDS
        cache.set(cache_key, listed_blocks, timeout=timeout)

    return listed_blocks


def list_blocks(recording: SessionRecording) -> list[RecordingBlock]:
    """
    Returns a list of recording blocks with their timestamps and URLs.
    The blocks are sorted by start time and guaranteed to start from the beginning of the recording.
    Returns an empty list if the recording is invalid or incomplete.
    """
    recording_blocks = load_blocks(recording)
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
            session_id=recording.session_id,
            team_id=recording.team.id,
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
