"""Driver-specific metadata discovery for SQL sources.

Every SQL source (`postgres/postgres.py`, `mysql/mysql.py`, etc.) needs the
same kinds of introspection queries at sync time:

- What are the primary keys of this table?
- What are the column types — enough to build a PyArrow schema?
- How many rows does the filtered sync produce?
- How big is the average row — so we can choose a safe chunk size?
- How big is the whole table — so we can choose a safe partition count?
- Is there an index whose leading column is our incremental cursor —
  so we can `FORCE INDEX` when the optimizer picks a bad plan?

Historically each source re-implemented all of those as free functions
(`_get_primary_keys`, `_get_table`, `_get_rows_to_sync`, `_get_partition_settings`,
`_get_table_average_row_size`, `_get_table_chunk_size`, `_find_index_for_cursor`, …)
with driver-specific SQL hardcoded inline. The query strings were the only
thing that actually differed between drivers — the partitioning math and
chunk-size math are identical.

`SchemaExplorer` is the uniform interface those helpers should go through.
Subclasses implement the driver-specific **queries** (pure abstract hooks);
the **math** (partition sizing, chunk sizing) lives in the base class so it's
consistent across every source.

Adding a new SQL source amounts to subclassing `SchemaExplorer`, filling in
six query methods, and wiring it into the source's streaming function — no
more copy-pasting `_get_partition_settings` with a slightly different SQL
dialect.
"""

from __future__ import annotations

import math
import dataclasses
from abc import ABC, abstractmethod
from typing import Any, Generic, Protocol, TypeVar

from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.utils import DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES
from posthog.temporal.data_imports.sources.common.sql.types import Column, Table

from products.data_warehouse.backend.types import PartitionSettings


class _CursorLike(Protocol):
    """The bare minimum surface we use on a DB-API cursor.

    Narrow Protocol (instead of typing against `pymysql.cursors.Cursor`,
    `psycopg2.extensions.cursor`, etc.) so the base class stays
    driver-agnostic. Concrete explorers are `Generic[CursorT]` and can
    tighten this to their real cursor type.
    """

    def execute(self, query: str, args: Any = ...) -> Any: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> Any: ...


CursorT = TypeVar("CursorT", bound=_CursorLike)
ColumnT = TypeVar("ColumnT", bound=Column)


@dataclasses.dataclass(frozen=True)
class TableStats:
    """Table-level statistics used to compute partition settings.

    Populated from driver-specific metadata tables — `information_schema.TABLES`
    on MySQL, `pg_class` on Postgres, etc. Both values are estimates: nothing
    downstream needs them to be exact, they just need to be close enough to
    pick a reasonable partition size.
    """

    table_size_bytes: int
    row_count: int


class SchemaExplorer(Generic[CursorT, ColumnT], ABC):
    """Driver-agnostic facade over a SQL source's metadata queries.

    Subclasses fill in the six abstract query methods. The base class composes
    those into the higher-level `get_partition_settings` / `get_chunk_size`
    operations so the sizing math is shared across drivers.

    All methods take an explicit `cursor` so the caller controls the
    connection lifecycle — an explorer is stateless and cheap to construct.
    """

    # ------------------------------------------------------------------
    # Abstract queries — one per piece of metadata, filled in per driver
    # ------------------------------------------------------------------

    @abstractmethod
    def get_primary_keys(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
    ) -> list[str] | None:
        """Return the primary-key column names for `schema.table_name`, or None."""

    @abstractmethod
    def get_table(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
    ) -> Table[ColumnT]:
        """Return column metadata rich enough to produce a PyArrow schema."""

    @abstractmethod
    def get_rows_to_sync(
        self,
        cursor: CursorT,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce. Returns 0 on error."""

    @abstractmethod
    def fetch_table_stats(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return a `(table_size_bytes, row_count)` estimate, or None when unavailable."""

    @abstractmethod
    def fetch_average_row_size(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Return the average row size in bytes sampled from the filtered query, or None."""

    @abstractmethod
    def find_index_for_cursor(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        cursor_field: str,
        logger: FilteringBoundLogger,
    ) -> str | None:
        """Return an index whose leading column is `cursor_field`, or None."""

    # ------------------------------------------------------------------
    # Shared sizing math — identical across every SQL driver today
    # ------------------------------------------------------------------

    def get_partition_settings(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
        partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    ) -> PartitionSettings | None:
        """Compute `PartitionSettings` from the driver's table stats.

        Subclasses only need to implement `fetch_table_stats` — this base
        method does the math. Returns None when stats are missing or the
        table is empty; the caller decides what to do in that case.
        """
        try:
            stats = self.fetch_table_stats(cursor, schema, table_name, logger)
        except Exception as e:
            logger.debug(f"get_partition_settings: Error fetching stats: {e}. Returning None", exc_info=e)
            capture_exception(e)
            return None

        if stats is None or stats.row_count == 0:
            logger.debug("get_partition_settings: no usable stats returning None")
            return None

        avg_row_size = stats.table_size_bytes / stats.row_count
        if avg_row_size <= 0:
            logger.debug("get_partition_settings: non-positive avg_row_size, returning None")
            return None

        # A partition must hold at least one row.
        partition_size = max(round(partition_size_bytes / avg_row_size), 1)
        partition_count = math.floor(stats.row_count / partition_size)

        if partition_count == 0:
            logger.debug(f"get_partition_settings: partition_count == 0, returning partition_size={partition_size}")
            return PartitionSettings(partition_count=1, partition_size=partition_size)

        logger.debug(f"get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
        return PartitionSettings(partition_count=partition_count, partition_size=partition_size)

    def get_chunk_size(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
        default_chunk_size: int = DEFAULT_CHUNK_SIZE,
        target_chunk_size_bytes: int = DEFAULT_TABLE_SIZE_BYTES,
    ) -> int:
        """Compute a safe `fetchmany` chunk size from the sampled average row size.

        Falls back to `default_chunk_size` whenever sampling fails — matching
        what every source does today.
        """
        try:
            row_size_bytes = self.fetch_average_row_size(
                cursor, schema, table_name, inner_query, inner_query_args, logger
            )
        except Exception as e:
            logger.debug(
                f"get_chunk_size: Error: {e}. Using default_chunk_size={default_chunk_size}",
                exc_info=e,
            )
            capture_exception(e)
            return default_chunk_size

        if row_size_bytes is None or row_size_bytes <= 0:
            logger.debug(f"get_chunk_size: Could not calculate row size. Using default_chunk_size={default_chunk_size}")
            return default_chunk_size

        chunk_size = int(target_chunk_size_bytes / row_size_bytes)
        if chunk_size < 1:
            chunk_size = 1
        logger.debug(
            f"get_chunk_size: row_size_bytes={row_size_bytes}. "
            f"target_chunk_size_bytes={target_chunk_size_bytes}. Using CHUNK_SIZE={chunk_size}"
        )
        return chunk_size
