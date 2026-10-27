import decimal
from pathlib import Path

import pyarrow as pa
import deltalake

from posthog.temporal.data_modeling.activities.materialize_view import _combine_batches


def _ipc_batch_with_buffers_off_a_16_byte_boundary() -> pa.RecordBatch:
    """Read a record batch the way the ClickHouse stream reader does: zero-copy over the IPC bytes.

    IPC only pads buffers to 8 bytes, so a decimal128 buffer can start 8 bytes off a 16-byte
    boundary. The message is placed 8 bytes into an aligned allocation to make that deterministic.
    """
    batch = pa.RecordBatch.from_arrays(
        [pa.array([decimal.Decimal("1.5"), decimal.Decimal("2.25")], pa.decimal128(38, 10))], names=["amount"]
    )
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    messages = pa.ipc.MessageReader.open_stream(sink.getvalue())
    schema = pa.ipc.read_schema(messages.read_next_message())
    message = messages.read_next_message().serialize()

    allocation = pa.allocate_buffer(message.size + 8)
    memoryview(allocation)[8 : 8 + message.size] = memoryview(message)
    read = pa.ipc.read_record_batch(pa.ipc.read_message(allocation.slice(8, message.size)), schema)

    assert read.column("amount").buffers()[1].address % 16 == 8
    return read


def test_a_single_streamed_batch_with_a_decimal_column_can_be_written_to_delta(tmp_path: Path) -> None:
    batch = _combine_batches([_ipc_batch_with_buffers_off_a_16_byte_boundary()])

    deltalake.write_deltalake(str(tmp_path), batch)

    assert deltalake.DeltaTable(str(tmp_path)).to_pyarrow_table().column("amount").to_pylist() == [
        decimal.Decimal("1.5"),
        decimal.Decimal("2.25"),
    ]
