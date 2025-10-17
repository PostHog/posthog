import asyncio
import collections.abc

import pyarrow as pa

from posthog.temporal.common.logger import get_write_only_logger

logger = get_write_only_logger()

CONTINUATION_BYTES = b"\xff\xff\xff\xff"


class InvalidMessageFormat(Exception):
    pass


class AsyncMessageReader:
    """Asynchronously read PyArrow messages from bytes iterator."""

    def __init__(self, bytes_iter: collections.abc.AsyncIterator[bytes]):
        self._bytes = bytes_iter
        self._buffer = bytearray()

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
            raise InvalidMessageFormat(
                f"Encapsulated IPC message format must begin with continuation bytes, received: '{self._buffer}'"
            )

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

        return msg

    async def read_until(self, n: int) -> None:
        """Read from self._bytes until there are at least n bytes in self._buffer."""
        while len(self._buffer) < n:
            bytes = await anext(self._bytes)
            self._buffer.extend(bytes)

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

    def __init__(self, bytes_iter: collections.abc.AsyncIterator[bytes]) -> None:
        self._reader = AsyncMessageReader(bytes_iter)
        self._schema: None | pa.Schema = None

    def __aiter__(self) -> "AsyncRecordBatchReader":
        return self

    async def __anext__(self) -> pa.RecordBatch:
        return await self.read_next_record_batch()

    async def read_next_record_batch(self) -> pa.RecordBatch:
        if self._schema is None:
            schema = await self.read_schema()
            self._schema = schema
        else:
            schema = self._schema

        message = await anext(self._reader)

        return pa.ipc.read_record_batch(message, schema)

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
