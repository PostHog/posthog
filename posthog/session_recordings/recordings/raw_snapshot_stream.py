import asyncio
from collections.abc import AsyncIterator, Sequence

from django.conf import settings

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.session_recordings.recordings.recording_api_client import RecordingApiClient, recording_api_client
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
        async with recording_api_client() as client:
            return await self._fetch_batch(client, 0)

    async def chunks_after(self, first_chunk: bytes) -> AsyncIterator[bytes]:
        yield first_chunk
        if len(self._batches) < 2:
            return
        try:
            async with recording_api_client() as client:
                for index in range(1, len(self._batches)):
                    yield await self._fetch_batch(client, index)
        except Exception as e:
            # The status is already sent, so re-raise: a stream that ends normally looks like a complete recording.
            capture_exception(
                e, {"location": "raw_snapshot_stream", "session_id": self._session_id, "team_id": self._team_id}
            )
            raise

    async def _fetch_batch(self, client: RecordingApiClient, index: int) -> bytes:
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
