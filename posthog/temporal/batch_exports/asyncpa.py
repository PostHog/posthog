import typing

import pyarrow as pa

CONTINUATION_BYTES = b"\xff\xff\xff\xff"


class InvalidMessageFormat(Exception):
    pass


class AsyncMessageReader:
    """Asynchronously read pyarrow.Messages from a stream of bytes."""

    def __init__(self, bytes_iter: typing.AsyncIterator[bytes]):
        self._bytes = bytes_iter
        self._buffer = bytearray()  # Mutable, in contrast to bytes()

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
            raise InvalidMessageFormat("Encapsulated IPC message format must begin with continuation bytes")

        await self.read_until(8)

        # Size of the metadata message + padding to 8-byte boundary.
        metadata_size = int.from_bytes(self._buffer[4:8], byteorder="little")

        if not metadata_size:
            raise StopAsyncIteration()

        await self.read_until(8 + metadata_size)

        metadata_flatbuffer = self._buffer[8:][:metadata_size]

        body_size = self.parse_body_size(metadata_flatbuffer)

        total_message_size = 8 + metadata_size + body_size
        await self.read_until(total_message_size)

        msg = pa.ipc.read_message(memoryview(self._buffer)[:total_message_size])

        self._buffer = self._buffer[total_message_size:]  # Reset buffer

        return msg

    async def read_until(self, n: int) -> None:
        """Read from self._bytes until there are at least n bytes in self._buffer."""
        while len(self._buffer) < n:
            self._buffer.extend(await anext(self._bytes))

    def parse_body_size(self, metadata_flatbuffer: bytearray) -> int:
        """Parse body size from metadata flatbuffer.

        Apache Arrow sends messages in an encapsulated interprocess communication format. This format includes
        a serialized Flatbuffer with the messages metadata. This method takes this `metadata_flatbuffer`, and
        locates and parses the message's body size. This way, the whole body can be read and parsed.

        Parsing the body size requires traversing the serialized Flatbuffer.

        References:
            See: https://github.com/dvidelabs/flatcc/blob/master/doc/binary-format.md#internals.
            See Apache Arrow Message schema: https://github.com/apache/arrow/blob/main/format/Message.fbs#L150.
            See MetadataVersion: https://github.com/apache/arrow/blob/main/format/Schema.fbs#L30
        """
        # By default, all content is little endian.
        # The first location contains a 32 bit (4 byte) offset to the root table.
        root_table_offset = int.from_bytes(metadata_flatbuffer[:4], byteorder="little", signed=False)
        # Root table starts with a 32 bit (4 byte) vtable offset, it is signed as its default negative.
        v_table_offset = int.from_bytes(metadata_flatbuffer[root_table_offset:][:4], byteorder="little", signed=True)
        # Vtable is found by substracting the signed 'v_table_offset' to the offset where 'v_table_offset' is stored.
        # Since 'v_table_offset' is stored at the beginning of the root table:
        v_table_location_offset = root_table_offset - v_table_offset

        # The vtable is a table of 16 bit (2 byte) offsets. The first entry is the vtable size in bytes.
        v_table_size = int.from_bytes(metadata_flatbuffer[v_table_location_offset:][:2], byteorder="little")
        # The second entry is another 2 byte offset indicating the object inline data size, which we are not interested in.
        # What follows is the actual object inline data, which is stored as offset to fields from the start of the root table.
        body_size_v_table_offset = 4  # This is the offset to the beginning of the Apache Arrow Message.
        # We are interested in parsing the body size, which comes after the version number, and header.
        # The version number is a short (16 bits, or 2 bytes).
        body_size_v_table_offset += 2
        # The header is a union type, so it has an entry indicating its type, and an entry with the offset to the header.
        body_size_v_table_offset += 4  # Adding 4 bytes for both entries.

        if v_table_size <= body_size_v_table_offset:
            # The Message contains no body or the format is unknown.
            body_size = 0
        else:
            # Everything in the vtable is an offset in the root table, so we get the one for the body size.
            body_size_offset = int.from_bytes(
                metadata_flatbuffer[v_table_location_offset + body_size_v_table_offset :][:2], byteorder="little"
            )
            # And the actual data is in the root table.
            body_size = int.from_bytes(
                metadata_flatbuffer[root_table_offset + body_size_offset :][:8], byteorder="little"
            )

        return body_size


class AsyncRecordBatchReader:
    """Asynchronously read PyArrow RecordBatches from an iterator of bytes."""

    def __init__(self, bytes_iter: typing.AsyncIterator[bytes]) -> None:
        self._reader = AsyncMessageReader(bytes_iter)
        self._schema = None

    def __aiter__(self) -> "AsyncRecordBatchReader":
        return self

    async def __anext__(self) -> pa.RecordBatch:
        return await self.read_next_record_batch()

    async def read_next_record_batch(self) -> pa.RecordBatch:
        """Read next pyarrow.RecordBatch.

        Will first parse the schema if not parsed yet.
        """
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
