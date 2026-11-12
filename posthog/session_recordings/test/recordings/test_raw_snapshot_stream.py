import asyncio
from typing import Any

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from posthog.session_recordings.recordings.errors import BlockFetchError
from posthog.session_recordings.recordings.raw_snapshot_stream import RAW_SNAPSHOT_STREAM_BATCH_SIZE, RawSnapshotStream
from posthog.session_recordings.session_recording_v2_service import RecordingBlock


def _block(index: int) -> RecordingBlock:
    return RecordingBlock(
        key=f"key{index}",
        start_byte=0,
        end_byte=10,
        start_timestamp="2026-01-01T00:00:00Z",
        end_timestamp="2026-01-01T00:00:01Z",
    )


class TestRawSnapshotStream(SimpleTestCase):
    @patch("posthog.session_recordings.recordings.raw_snapshot_stream.recording_api_client")
    def test_streams_every_block_in_stored_order_as_one_line_each(self, mock_recording_api_client: MagicMock) -> None:
        block_count = RAW_SNAPSHOT_STREAM_BATCH_SIZE * 2 + 1

        async def fetch_block(key: str, *_args: Any, **_kwargs: Any) -> bytes:
            index = int(key.removeprefix("key"))
            line = b'["window",{"block":%d}]' % index
            # Storage ends some blocks with a newline and some without one.
            return line + b"\n" if index % 2 else line

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(side_effect=fetch_block)
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage
        stream = RawSnapshotStream("session", 1, [_block(i) for i in range(block_count)])

        async def read() -> list[bytes]:
            first_chunk = await stream.first_chunk()
            return [chunk async for chunk in stream.chunks_after(first_chunk)]

        chunks = asyncio.run(read())

        assert len(chunks) == 3
        assert b"".join(chunks) == b"".join(b'["window",{"block":%d}]\n' % i for i in range(block_count))

    @patch("posthog.session_recordings.recordings.raw_snapshot_stream.capture_exception")
    @patch("posthog.session_recordings.recordings.raw_snapshot_stream.recording_api_client")
    def test_block_failure_after_the_first_batch_ends_the_stream_with_an_error(
        self, mock_recording_api_client: MagicMock, _mock_capture_exception: MagicMock
    ) -> None:
        async def fetch_block(key: str, *_args: Any, **_kwargs: Any) -> bytes:
            if key == f"key{RAW_SNAPSHOT_STREAM_BATCH_SIZE}":
                raise BlockFetchError("Block not found")
            return b"{}"

        mock_storage = MagicMock()
        mock_storage.fetch_block = AsyncMock(side_effect=fetch_block)
        mock_recording_api_client.return_value.__aenter__.return_value = mock_storage
        stream = RawSnapshotStream("session", 1, [_block(i) for i in range(RAW_SNAPSHOT_STREAM_BATCH_SIZE + 1)])

        async def read() -> list[bytes]:
            first_chunk = await stream.first_chunk()
            return [chunk async for chunk in stream.chunks_after(first_chunk)]

        with self.assertRaises(BlockFetchError):
            asyncio.run(read())
