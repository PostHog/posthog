import sys
from typing import Any, Optional

import pyarrow as pa
import pyarrow.compute as pc
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list

DEFAULT_CHUNK_SIZE_BYTES: int = 200 * 1024 * 1024  # 200 MiB
DEFAULT_CHUNK_SIZE: int = 5000

# pyarrow `string`/`binary`/`list` columns use 32-bit offsets, so a single column in
# one batch overflows once its offsets cross 2^31 (~2.1e9). delta-rs concatenates a
# merge source's chunks into one contiguous array, which is where this surfaces in
# prod as "Offset overflow error: <bytes>". Casting the source to large_string does
# NOT help — delta-rs coerces back to the target's 32-bit `string` during the merge —
# so the only reliable fix is to keep each yielded table's worst column under the
# limit, splitting by rows when needed. The margin below 2^31 leaves room for the
# offset buffer itself and any target-side rows pulled into a matched-update merge.
DEFAULT_MAX_COLUMN_OFFSET_BYTES: int = 1_500_000_000  # ~1.4 GiB


def _column_offset_pressure(col: pa.ChunkedArray) -> int:
    """Return the 32-bit-offset quantity that would overflow for this column.

    For `string`/`binary` it's the total value bytes (the final offset). For `list`
    it's the total child element count (the final list offset). 64-bit (`large_*`)
    variants can't overflow, so they contribute nothing. Computed via `pc.sum` over
    per-row lengths, which is slice-accurate (unlike `Array.nbytes`, which reports the
    full shared buffer for a zero-copy slice and would break the recursion below).
    """
    t = col.type
    if pa.types.is_string(t) or pa.types.is_binary(t):
        total = pc.sum(pc.binary_length(col)).as_py()
        return int(total or 0)
    if pa.types.is_list(t):
        total = pc.sum(pc.list_value_length(col)).as_py()
        return int(total or 0)
    return 0


def _max_offset_pressure(table: pa.Table) -> int:
    return max((_column_offset_pressure(table.column(name)) for name in table.column_names), default=0)


def _split_to_offset_limit(table: pa.Table, limit: int) -> list[pa.Table]:
    """Recursively row-halve `table` until every slice's worst column is under `limit`.

    Slices are zero-copy views, so this doesn't duplicate the data. A single row can
    never overflow (a string value can't itself exceed 2^31), so the `num_rows <= 1`
    base case guarantees termination.
    """
    if table.num_rows <= 1 or _max_offset_pressure(table) <= limit:
        return [table]

    mid = table.num_rows // 2
    left = table.slice(0, mid)
    right = table.slice(mid, table.num_rows - mid)
    return _split_to_offset_limit(left, limit) + _split_to_offset_limit(right, limit)


class Batcher:
    _buffer: list[Any]
    _buffer_size_bytes: int
    _ready: list[pa.Table]
    _logger: FilteringBoundLogger
    _chunk_size: int
    _chunk_size_bytes: int
    _max_column_offset_bytes: int

    def __init__(
        self,
        logger: FilteringBoundLogger,
        chunk_size: Optional[int] = None,
        chunk_size_bytes: Optional[int] = None,
        max_column_offset_bytes: Optional[int] = None,
    ) -> None:
        self._logger = logger

        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self._chunk_size_bytes = chunk_size_bytes or DEFAULT_CHUNK_SIZE_BYTES
        self._max_column_offset_bytes = max_column_offset_bytes or DEFAULT_MAX_COLUMN_OFFSET_BYTES

        self._buffer = []
        self._buffer_size_bytes = 0
        self._ready = []

    def _set_ready(self, table: pa.Table) -> None:
        """Split `table` so no yielded chunk can overflow a 32-bit offset column."""
        self._ready = _split_to_offset_limit(table, self._max_column_offset_bytes)

    def _estimate_size(self, obj: Any) -> int:
        if isinstance(obj, dict):
            return sys.getsizeof(obj) + sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
        elif isinstance(obj, list | tuple | set):
            return sys.getsizeof(obj) + sum(self._estimate_size(i) for i in obj)
        else:
            return sys.getsizeof(obj)

    def batch(self, item: list[Any] | dict | pa.Table) -> None:
        if self._ready:
            raise Exception("Batcher already has a table ready to yield. Call get_table() before batching more items.")

        if isinstance(item, list):
            if len(self._buffer) > 0:
                self._buffer.extend(item)
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(self._buffer) >= self._chunk_size:
                    self._logger.debug(f"Processing buffer (list). Length of buffer = {len(self._buffer)}")

                    self._set_ready(table_from_py_list(self._buffer))
                else:
                    return
            else:
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(item) >= self._chunk_size:
                    self._logger.debug(f"Processing item (list). Length of item = {len(item)}")
                    self._set_ready(table_from_py_list(item))
                else:
                    self._buffer.extend(item)
                    return
        elif isinstance(item, dict):
            self._buffer.append(item)
            self._buffer_size_bytes += self._estimate_size(item)
            if self._buffer_size_bytes < self._chunk_size_bytes and len(self._buffer) < self._chunk_size:
                return

            self._logger.debug(f"Processing buffer (dict). Length of buffer = {len(self._buffer)}")
            self._set_ready(table_from_py_list(self._buffer))
        elif isinstance(item, pa.Table):
            self._set_ready(item)
        else:
            raise Exception(f"Unhandled item type: {item.__class__.__name__}")

        # `_set_ready` clears the buffer's contribution; reset the byte counter so the
        # next batching cycle starts fresh.
        self._buffer = []
        self._buffer_size_bytes = 0

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        if include_incomplete_chunk:
            return len(self._ready) > 0 or len(self._buffer) > 0

        return len(self._ready) > 0

    def get_table(self) -> pa.Table:
        if not self._ready and len(self._buffer) > 0:
            self._logger.debug(f"Processing leftover buffer. Length of buffer = {len(self._buffer)}")
            self._set_ready(table_from_py_list(self._buffer))
            self._buffer = []
            self._buffer_size_bytes = 0

        if self._ready:
            return self._ready.pop(0)

        raise Exception("No chunks available to yield")
