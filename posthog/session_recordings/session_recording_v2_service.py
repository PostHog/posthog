from datetime import datetime
from typing import TypedDict
import structlog

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

logger = structlog.get_logger(__name__)


class RecordingBlock(TypedDict):
    start_time: datetime
    end_time: datetime
    url: str


def list_blocks(recording: SessionRecording) -> list[RecordingBlock]:
    """
    Returns a list of recording blocks with their timestamps and URLs.
    The blocks are sorted by start time and guaranteed to start from the beginning of the recording.
    Returns an empty list if the recording is invalid or incomplete.
    """
    metadata = SessionReplayEvents().list_blocks(recording.session_id, recording.team)
    if not metadata:
        return []

    first_timestamps = metadata.block_first_timestamps
    last_timestamps = metadata.block_last_timestamps
    urls = metadata.block_urls

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
        {
            "start_time": start_time,
            "end_time": end_time,
            "url": url,
        }
        for start_time, end_time, url in zip(first_timestamps, last_timestamps, urls)
    ]

    blocks.sort(key=lambda b: b["start_time"])

    # If we started recording halfway through the session, we should not return any blocks
    # as we don't have the complete recording from the start
    if not blocks or not metadata.start_time or blocks[0]["start_time"] != metadata.start_time:
        return []

    return blocks
