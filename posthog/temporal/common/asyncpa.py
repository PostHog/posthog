import asyncio
import collections.abc

import pyarrow as pa

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger()

CONTINUATION_BYTES = b"\xff\xff\xff\xff"

# How many leading bytes to surface when the stream is not Arrow, so the error can show the
# server's actual response (often a plain-text error) instead of a byte-level complaint.
INVALID_PREFIX_PREVIEW_BYTES = 256


class InvalidMessageFormat(Exception):
    pass


def describe_invalid_prefix(preview: bytes) -> str:
    """Build a readable error for a stream that is not a valid Arrow IPC message.

    Each Arrow IPC message starts with a continuation marker. When the first bytes are something
    else, the body is not Arrow: the source returned an error, or an HTTP framing artifact leaked
    in undecoded. The raw byte complaint means nothing to a reader, so decode and show what
    actually arrived, which is usually the error text itself.
    """
    detail = preview.decode("utf-8", errors="replace")
    return (
        "Expected an Arrow record batch, but the stream did not start with the Arrow continuation "
        "marker. The source returned an error or non-Arrow content instead of Arrow record batches. "
        f"The stream started with: {detail!r}"
    )


class AsyncMessageReader:
    """Asynchronously read PyArrow messages from bytes iterator."""

    def __init__(self, bytes_iter: collections.abc.AsyncIterator[bytes]):
        self._bytes = bytes_iter
        self._buffer = bytearray()
        self._bytes_consumed = 0

    @property
    def bytes_consumed(self) -> int:
        """Total bytes of fully parsed IPC messages consumed from the stream.

        Buffered but not yet parsed bytes are not counted, so this is always an
        offset at an IPC message boundary.
        """
        return self._bytes_consumed

    def __aiter__(self) -> "AsyncMessageReader":
        return self

    async def __anext__(self) -> pa.Message:
        return await self.read_next_message()

    async def read_next_message(self) -> pa.Message:
        """Read the next message as an encapsulated IPC binary message.

        See: https://arrow.apache.org/docs/format/Columnar.html#encapsulated-message-format.
        """
        await self.read_until(4)

        if self._buffer[:4] != CONTINUATION_BYTES:
            preview = await self.read_preview()
            raise InvalidMessageFormat(describe_invalid_prefix(preview))

        await self.read_until(8)

        # Size of the metadata message + padding to 8-byte boundary.
        metadata_size = int.from_bytes(self._buffer[4:8], byteorder="little")

        if not metadata_size:
            raise StopAsyncIteration()

        await self.read_until(8 + metadata_size)

        with memoryview(self._buffer) as buffer_view:
            metadata_flatbuffer = buffer_view[8:][:metadata_size]
            body_size = self.parse_body_size(metadata_flatbuffer)

        del metadata_flatbuffer

        total_message_size = 8 + metadata_size + body_size
        await self.read_until(total_message_size)

        with memoryview(self._buffer) as buffer_view:
            loop = asyncio.get_running_loop()
            msg = await loop.run_in_executor(None, pa.ipc.read_message, buffer_view[:total_message_size])

        self._buffer = self._buffer[total_message_size:]
        self._bytes_consumed += total_message_size

        return msg

    async def read_until(self, n: int) -> None:
        """Read from self._bytes until there are at least n bytes in self._buffer."""
        while len(self._buffer) < n:
            bytes = await anext(self._bytes)
            self._buffer.extend(bytes)

    async def read_preview(self) -> bytes:
        """Pull a little more of the stream so an error can show what actually arrived.

        Best-effort: this only enriches an error we are about to raise. A short stream ends with
        StopAsyncIteration, but a truncated or aborted body raises a transport error instead (an
        aiohttp payload error from ClickHouse, a botocore streaming error from S3), and letting
        that escape would replace the readable format error with a byte-level transport complaint.
        So fall back to whatever is already buffered on any Exception. Cancellation is a
        BaseException, so it still propagates.
        """
        try:
            await self.read_until(INVALID_PREFIX_PREVIEW_BYTES)
        except Exception:
            pass
        return bytes(self._buffer[:INVALID_PREFIX_PREVIEW_BYTES])

    def parse_body_size(self, metadata_flatbuffer: bytes | bytearray | memoryview) -> int:
        """Parse body size from metadata flatbuffer.

        See: https://github.com/dvidelabs/flatcc/blob/master/doc/binary-format.md#internals.
        """
        # All content is little endian, and most offsets are 4 bytes.
        # The first location points to root table.
        root_table_location = int.from_bytes(metadata_flatbuffer[:4], byteorder="little", signed=False)
        # Root table starts with a 4 byte vtable offset, it is signed.
        v_table_offset = int.from_bytes(metadata_flatbuffer[root_table_location:][:4], byteorder="little", signed=True)
        # Vtable is found by substracting the signed 'v_table_offset' to the location where 'v_table_offset' is stored.
        # This 'v_table_offset' is stored in the root table, hence the following substraction:
        v_table_location = root_table_location - v_table_offset

        # The vtable is a table of 2 byte offsets. The first entry is the vtable size in bytes.
        v_table_size = int.from_bytes(metadata_flatbuffer[v_table_location:][:2], byteorder="little")
        # The second entry is another 2 byte offset indicating the table size, which we are not interested in.
        # We know that a Message contains the following: a version number, a header, the body size, and custom metadata.
        # We are interested in parsing the body size, which comes after the first two vtable entries, the version number, and header.
        # So, we skip until 10 (4 bytes for vtable entries, 2 bytes for version number, 2 bytes for header type, 2 bytes for header).
        body_size_v_table_offset = 10

        if v_table_size <= body_size_v_table_offset:
            body_size = 0
        else:
            body_size_offset = int.from_bytes(
                metadata_flatbuffer[v_table_location + body_size_v_table_offset :][:2], byteorder="little"
            )
            body_size = int.from_bytes(
                metadata_flatbuffer[root_table_location + body_size_offset :][:8], byteorder="little"
            )

        return body_size


class AsyncRecordBatchReader:
    """Asynchronously read PyArrow RecordBatches from an iterator of bytes."""

    def __init__(self, bytes_iter: collections.abc.AsyncIterator[bytes], schema: pa.Schema | None = None) -> None:
        """Initialize the reader.

        Arguments:
            bytes_iter: The stream of bytes to read record batches from.
            schema: Pass a schema parsed from a previous read to resume a stream
                mid-way: the stream is then expected to start at a record batch
                message boundary, with no schema message.
        """
        self._reader = AsyncMessageReader(bytes_iter)
        self._schema: None | pa.Schema = schema

    @property
    def bytes_consumed(self) -> int:
        return self._reader.bytes_consumed

    @property
    def schema(self) -> pa.Schema | None:
        return self._schema

    def __aiter__(self) -> "AsyncRecordBatchReader":
        return self

    async def __anext__(self) -> pa.RecordBatch:
        return await self.read_next_record_batch()

    async def read_next_record_batch(self) -> pa.RecordBatch:
        schema = await self.get_schema()
        message = await anext(self._reader)

        return pa.ipc.read_record_batch(message, schema)

    async def get_schema(self) -> pa.Schema:
        if self._schema is None:
            self._schema = await self.read_schema()
        return self._schema

    async def read_schema(self) -> pa.Schema:
        """Read the schema, which should be the first message."""
        message = await anext(self._reader)

        if message.type != "schema":
            raise TypeError(f"Expected message of type 'schema' got '{message.type}'")

        return pa.ipc.read_schema(message)


class AsyncRecordBatchProducer(AsyncRecordBatchReader):
    def __init__(self, bytes_iter: collections.abc.AsyncIterator[bytes]) -> None:
        super().__init__(bytes_iter)

    async def produce(self, queue: asyncio.Queue[pa.RecordBatch]):
        """Read all record batches and produce them to a queue for async processing."""
        await logger.adebug("Starting record batch produce loop")

        while True:
            try:
                record_batch = await self.read_next_record_batch()
            except StopAsyncIteration:
                await logger.adebug("No more record batches to produce, closing loop")
                return
            except Exception as e:
                await logger.aexception("Unexpected error occurred while producing record batches", exc_info=e)
                raise

            await queue.put(record_batch)
