import sys
from typing import Any, Optional

import pyarrow as pa
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list

DEFAULT_CHUNK_SIZE_BYTES: int = 200 * 1024 * 1024  # 200 MiB
DEFAULT_CHUNK_SIZE: int = 5000


class Batcher:
    _buffer: list[Any]
    _buffer_size_bytes: int
    _py_table: pa.Table | None = None
    _logger: FilteringBoundLogger
    _chunk_size: int
    _chunk_size_bytes: int

    def __init__(
        self, logger: FilteringBoundLogger, chunk_size: Optional[int] = None, chunk_size_bytes: Optional[int] = None
    ) -> None:
        self._logger = logger

        self._chunk_size = chunk_size or DEFAULT_CHUNK_SIZE
        self._chunk_size_bytes = chunk_size_bytes or DEFAULT_CHUNK_SIZE_BYTES

        self._buffer = []
        self._buffer_size_bytes = 0
        self._py_table = None

    def _estimate_size(self, obj: Any) -> int:
        if isinstance(obj, dict):
            return sys.getsizeof(obj) + sum(self._estimate_size(k) + self._estimate_size(v) for k, v in obj.items())
        elif isinstance(obj, list | tuple | set):
            return sys.getsizeof(obj) + sum(self._estimate_size(i) for i in obj)
        else:
            return sys.getsizeof(obj)

    def batch(self, item: list[Any] | dict | pa.Table) -> None:
        if self._py_table is not None:
            raise Exception("Batcher already has a table ready to yield. Call get_table() before batching more items.")

        if isinstance(item, list):
            if len(self._buffer) > 0:
                self._buffer.extend(item)
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(self._buffer) >= self._chunk_size:
                    self._logger.debug(f"Processing buffer (list). Length of buffer = {len(self._buffer)}")

                    self._py_table = table_from_py_list(self._buffer)
                else:
                    return
            else:
                self._buffer_size_bytes += self._estimate_size(item)
                if self._buffer_size_bytes >= self._chunk_size_bytes or len(item) >= self._chunk_size:
                    self._logger.debug(f"Processing item (list). Length of item = {len(item)}")
                    self._py_table = table_from_py_list(item)
                else:
                    self._buffer.extend(item)
                    return
        elif isinstance(item, dict):
            self._buffer.append(item)
            self._buffer_size_bytes += self._estimate_size(item)
            if self._buffer_size_bytes < self._chunk_size_bytes and len(self._buffer) < self._chunk_size:
                return

            self._logger.debug(f"Processing buffer (dict). Length of buffer = {len(self._buffer)}")
            self._py_table = table_from_py_list(self._buffer)
        elif isinstance(item, pa.Table):
            self._py_table = item
        else:
            raise Exception(f"Unhandled item type: {item.__class__.__name__}")

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        if include_incomplete_chunk:
            return self._py_table is not None or len(self._buffer) > 0

        return self._py_table is not None

    def get_table(self) -> pa.Table:
        if self._py_table is not None:
            table = self._py_table

            self._py_table = None
            self._buffer = []
            self._buffer_size_bytes = 0
            return table

        if len(self._buffer) > 0:
            self._logger.debug(f"Processing leftover buffer. Length of buffer = {len(self._buffer)}")
            table = table_from_py_list(self._buffer)

            self._buffer = []
            self._buffer_size_bytes = 0

            return table

        raise Exception("No chunks available to yield")
