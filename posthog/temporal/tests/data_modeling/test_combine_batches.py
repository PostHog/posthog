from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import deltalake

from posthog.temporal.data_modeling.activities.materialize_view import _combine_batches


def _misaligned(batch: pa.RecordBatch) -> bool:
    return any(buf.address % 16 for buf in batch.column(0).buffers() if buf is not None)


def _ipc_batch_with_misaligned_decimal(batch: pa.RecordBatch) -> pa.RecordBatch:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    stream = sink.getvalue().to_pybytes()
    for shift in (0, 8):
        read = pa.ipc.open_stream(pa.py_buffer(bytes(shift) + stream).slice(shift)).read_next_batch()
        if _misaligned(read):
            return read
    raise AssertionError("could not build a misaligned batch")


def test_single_decimal_batch_writes_to_delta(tmp_path: Path) -> None:
    decimal_batch = pa.RecordBatch.from_arrays(
        [pa.array([Decimal("1.5")], type=pa.decimal128(18, 10))],
        names=["amount"],
    )

    combined = _combine_batches([_ipc_batch_with_misaligned_decimal(decimal_batch)])
    deltalake.write_deltalake(str(tmp_path), combined, mode="overwrite")

    assert deltalake.DeltaTable(str(tmp_path)).to_pyarrow_table().column("amount").to_pylist() == [Decimal("1.5")]
