import asyncio
from collections.abc import AsyncIterator, Iterator, Sequence

from django.conf import settings

import posthoganalytics
from asgiref.sync import async_to_sync

from posthog.exceptions_capture import capture_exception
from posthog.session_recordings.recordings.recording_api_client import recording_api_client
from posthog.session_recordings.session_recording_v2_service import RecordingBlock

RAW_SNAPSHOT_STREAM_FLAG = "replay-raw-snapshot-stream"

# The number of blocks a stream fetches from recording-api in parallel, and so the most it holds in memory at once.
RAW_SNAPSHOT_STREAM_BATCH_SIZE = 20


def is_raw_snapshot_stream_enabled(team_id: int) -> bool:
    # The same targeting properties as is_direct_blocks_enabled, which explains them.
    person_properties: dict[str, str | int] = {"team_id": team_id}
    if settings.CLOUD_DEPLOYMENT:
        person_properties["cloud_deployment"] = settings.CLOUD_DEPLOYMENT
    try:
        return bool(
            posthoganalytics.feature_enabled(
                RAW_SNAPSHOT_STREAM_FLAG,
                str(team_id),
                person_properties=person_properties,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


class RawSnapshotStream:
    """A whole recording as JSONL, read from recording-api one batch of blocks at a time.

    Each line is a snapshot exactly as it was stored. The stream does not apply the processing that the web player
    applies after download, so compressed rrweb payloads stay compressed and mobile events stay in their own format.
    """

    def __init__(self, session_id: str, team_id: int, blocks: Sequence[RecordingBlock]) -> None:
        self._session_id = session_id
        self._team_id = team_id
        self._batches = [
            blocks[start : start + RAW_SNAPSHOT_STREAM_BATCH_SIZE]
            for start in range(0, len(blocks), RAW_SNAPSHOT_STREAM_BATCH_SIZE)
        ]

    async def first_chunk(self) -> bytes:
        """Fetch the first batch on its own, so that a caller can report a failure before it sends any headers."""
        return await self._chunk(0)

    async def chunks_after(self, first_chunk: bytes) -> AsyncIterator[bytes]:
        yield first_chunk
        for index in range(1, len(self._batches)):
            yield await self._later_chunk(index)

    def chunks_after_sync(self, first_chunk: bytes) -> Iterator[bytes]:
        """The same stream for a WSGI server, which reads an async iterator to its end before it sends any of it."""
        yield first_chunk
        for index in range(1, len(self._batches)):
            yield async_to_sync(self._later_chunk)(index)

    async def _later_chunk(self, index: int) -> bytes:
        try:
            return await self._chunk(index)
        except Exception as e:
            # The status is already sent, so re-raise: a stream that ends normally looks like a complete recording.
            capture_exception(
                e, {"location": "raw_snapshot_stream", "session_id": self._session_id, "team_id": self._team_id}
            )
            raise

    async def _chunk(self, index: int) -> bytes:
        # One client for each batch, because the WSGI stream runs every batch on its own event loop.
        async with recording_api_client() as client:
            contents = await asyncio.gather(
                *(
                    client.fetch_block(
                        block.key, block.start_byte, block.end_byte, self._session_id, self._team_id, decompress=True
                    )
                    for block in self._batches[index]
                )
            )
        return b"".join(_newline_terminated(content) for content in contents)


def _newline_terminated(content: bytes) -> bytes:
    if not content or content.endswith(b"\n"):
        return content
    return content + b"\n"
