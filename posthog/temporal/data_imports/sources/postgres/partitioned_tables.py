from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional

import psycopg
import pyarrow as pa
from psycopg import sql
from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    QueryTimeoutException,
    table_from_iterator,
)

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

# Max rows per FETCH when reading a partitioned parent table. A partitioned
# parent scan dispatches across every child partition; a large chunk size can
# blow past the source's statement_timeout even when per-row payload is small.
PARTITIONED_TABLE_MAX_CHUNK_SIZE = 10_000

# Retry budgets for iterate_date_windows. Counters reset on every successful
# window. Exhausting QueryCanceled surfaces QueryTimeoutException; exhausting
# SerializationFailure re-raises the original error so the caller can decide
# how to handle it (e.g. retry the whole sync at a higher level).
WINDOW_MAX_QUERY_CANCELED_RETRIES = 3
WINDOW_MAX_SERIALIZATION_RETRIES = 5

_RANGE_BOUND_RE = re.compile(r"FOR VALUES FROM \((.*)\) TO \((.*)\)", re.DOTALL)

_DATE_OR_NUMERIC_INCREMENTAL_TYPES: frozenset[IncrementalFieldType] = frozenset(
    {
        IncrementalFieldType.Date,
        IncrementalFieldType.DateTime,
        IncrementalFieldType.Timestamp,
        IncrementalFieldType.Integer,
        IncrementalFieldType.Numeric,
    }
)


@dataclass(frozen=True)
class ChildPartition:
    oid: int
    schema: str
    name: str
    partbound: str  # raw pg_get_expr(relpartbound, oid)


@dataclass(frozen=True)
class PartitionStrategy:
    strategy: Literal["r", "l", "h"]  # range | list | hash
    key_columns: tuple[str, ...]


def is_partitioned_table(cursor: psycopg.Cursor, schema: str, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_partitioned_table pt
            JOIN pg_class c ON c.oid = pt.partrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %(schema)s AND c.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def get_estimated_row_count_for_partitioned_table(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> int | None:
    """Approximate row count for a partitioned table via catalog stats.

    Tries pg_class.reltuples first (accurate after ANALYZE, -1 otherwise);
    falls back to pg_stat_user_tables.n_live_tup (stats collector). Returns
    None when neither source is reliable so the caller can run an exact
    COUNT(*).
    """
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN c.reltuples >= 0 THEN c.reltuples ELSE 0 END), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples < 0 THEN 1 ELSE 0 END), 0)::bigint,
            COALESCE(SUM(s.n_live_tup), 0)::bigint,
            COUNT(*)::bigint
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE i.inhparent = (
            SELECT c2.oid
            FROM pg_class c2
            JOIN pg_namespace n ON n.oid = c2.relnamespace
            WHERE n.nspname = %(schema)s AND c2.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()

    if row is None:
        logger.debug("get_estimated_row_count_for_partitioned_table: no result, returning None")
        return None

    reltuples_sum, unanalyzed_count, n_live_tup_sum, partition_count = (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
    )

    if partition_count == 0:
        logger.debug("get_estimated_row_count_for_partitioned_table: no child partitions, returning None")
        return None

    if unanalyzed_count == 0 and reltuples_sum > 0:
        logger.debug(f"get_estimated_row_count_for_partitioned_table: reltuples estimate = {reltuples_sum}")
        return reltuples_sum

    if n_live_tup_sum > 0:
        logger.debug(
            f"get_estimated_row_count_for_partitioned_table: reltuples unreliable "
            f"(unanalyzed_partitions={unanalyzed_count}/{partition_count}), "
            f"n_live_tup estimate = {n_live_tup_sum}"
        )
        return n_live_tup_sum

    logger.debug(
        f"get_estimated_row_count_for_partitioned_table: no reliable estimate "
        f"(reltuples={reltuples_sum}, unanalyzed={unanalyzed_count}/{partition_count}, "
        f"n_live_tup={n_live_tup_sum}), returning None"
    )
    return None


def get_partition_settings_for_partitioned_table(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    default_partition_target_size_in_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
) -> PartitionSettings | None:
    """Derive PartitionSettings for a partitioned parent via pg_inherits + catalog sizes."""
    import math

    cursor.execute(
        """
        SELECT
            COALESCE(SUM(pg_table_size(c.oid)), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples >= 0 THEN c.reltuples ELSE 0 END), 0)::bigint,
            COALESCE(SUM(CASE WHEN c.reltuples < 0 THEN 1 ELSE 0 END), 0)::bigint,
            COUNT(*)::bigint
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        WHERE i.inhparent = (
            SELECT c2.oid
            FROM pg_class c2
            JOIN pg_namespace n ON n.oid = c2.relnamespace
            WHERE n.nspname = %(schema)s AND c2.relname = %(table)s
        )
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()
    if row is None:
        return None

    total_size, total_rows, unanalyzed_count, partition_count_children = (
        int(row[0]),
        int(row[1]),
        int(row[2]),
        int(row[3]),
    )

    if partition_count_children == 0 or total_size == 0 or total_rows == 0 or unanalyzed_count > 0:
        logger.debug(
            f"get_partition_settings_for_partitioned_table: no reliable estimate "
            f"(children={partition_count_children}, size={total_size}, rows={total_rows}, "
            f"unanalyzed={unanalyzed_count}), returning None"
        )
        return None

    avg_row_size = total_size / total_rows
    # Floor partition_size at 1 so we never divide by zero when a row's average
    # size exceeds the partition target (e.g. wide JSONB columns).
    partition_size = max(1, round(default_partition_target_size_in_bytes / avg_row_size))
    partition_count = max(1, math.floor(total_rows / partition_size))
    logger.debug(
        f"get_partition_settings_for_partitioned_table: partition_count={partition_count}, "
        f"partition_size={partition_size} (total_rows={total_rows}, total_size={total_size})"
    )
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def list_child_partitions(cursor: psycopg.Cursor, schema: str, table_name: str) -> list[ChildPartition]:
    cursor.execute(
        """
        SELECT c.oid, n.nspname, c.relname, pg_get_expr(c.relpartbound, c.oid)
        FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.inhparent = (
            SELECT c2.oid
            FROM pg_class c2
            JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
            WHERE n2.nspname = %(schema)s AND c2.relname = %(table)s
        )
        ORDER BY c.relname
        """,
        {"schema": schema, "table": table_name},
    )
    return [
        ChildPartition(oid=int(r[0]), schema=str(r[1]), name=str(r[2]), partbound=str(r[3]) if r[3] else "")
        for r in cursor.fetchall()
    ]


def get_partition_strategy(cursor: psycopg.Cursor, schema: str, table_name: str) -> PartitionStrategy | None:
    cursor.execute(
        """
        SELECT pt.partstrat, array_agg(a.attname ORDER BY k.ord)
        FROM pg_partitioned_table pt
        JOIN pg_class c ON c.oid = pt.partrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN LATERAL unnest(pt.partattrs) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        LEFT JOIN pg_attribute a ON a.attrelid = pt.partrelid AND a.attnum = k.attnum
        WHERE n.nspname = %(schema)s AND c.relname = %(table)s
        GROUP BY pt.partstrat
        """,
        {"schema": schema, "table": table_name},
    )
    row = cursor.fetchone()
    if row is None:
        return None
    strat_raw = str(row[0])
    if strat_raw == "r":
        strat: Literal["r", "l", "h"] = "r"
    elif strat_raw == "l":
        strat = "l"
    elif strat_raw == "h":
        strat = "h"
    else:
        return None
    names = tuple(str(n) for n in (row[1] or []) if n is not None)
    return PartitionStrategy(strategy=strat, key_columns=names)


def _parse_bound_value(raw: str, field_type: IncrementalFieldType) -> Any | None:
    s = raw.strip()
    if s in ("MINVALUE", "MAXVALUE", "DEFAULT"):
        return None
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        s = s[1:-1]
    try:
        if field_type == IncrementalFieldType.Date:
            return datetime.strptime(s, "%Y-%m-%d").date()
        if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp):
            parsed = datetime.fromisoformat(s.replace(" ", "T"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        if field_type == IncrementalFieldType.Integer:
            return int(s)
        if field_type == IncrementalFieldType.Numeric:
            return float(s)
    except (ValueError, TypeError):
        return None
    return None


def partition_bounds_for_range(
    child: ChildPartition, incremental_field_type: IncrementalFieldType
) -> tuple[Any, Any] | None:
    """Parse 'FOR VALUES FROM (x) TO (y)' -> (lo, hi). None for default/list/hash/parse-fail."""
    if not child.partbound:
        return None
    m = _RANGE_BOUND_RE.match(child.partbound.strip())
    if not m:
        return None
    lo_raw, hi_raw = m.group(1), m.group(2)
    # multi-column partition keys include commas; skip those (we only support single-col here)
    if "," in lo_raw or "," in hi_raw:
        return None
    lo = _parse_bound_value(lo_raw, incremental_field_type)
    hi = _parse_bound_value(hi_raw, incremental_field_type)
    if lo is None or hi is None:
        return None
    return (lo, hi)


def derive_upper_bound(
    incremental_field_type: IncrementalFieldType,
    range_bounds: list[tuple[Any, Any]],
) -> Any | None:
    """Cheap upper bound for window walk, no MAX() scan.

    Priority: range partition max hi -> now() for time-based -> None (open-ended).
    """
    if range_bounds:
        return max(hi for _, hi in range_bounds)
    if incremental_field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp):
        return datetime.now(UTC)
    if incremental_field_type == IncrementalFieldType.Date:
        return datetime.now(UTC).date()
    return None


def should_preserve_asc_sort(
    strategy: PartitionStrategy | None,
    incremental_field: Optional[str],
) -> bool:
    """Per-partition / window iteration preserves ASC order only when range-partitioned
    on the incremental field. Hash/list partitioning interleaves values so the caller
    should tell downstream to treat rows as unordered.
    """
    if strategy is None or incremental_field is None:
        return True  # no strategy info -> default to asc, matches legacy behavior
    if strategy.strategy != "r":
        return False
    return incremental_field in strategy.key_columns


def _window_default(
    initial_window: timedelta | int | float | None,
    range_bounds: list[tuple[Any, Any]],
    field_type: IncrementalFieldType,
) -> Any:
    if initial_window is not None:
        return initial_window
    if range_bounds:
        widths = sorted(hi - lo for lo, hi in range_bounds)
        return widths[len(widths) // 2]
    if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp, IncrementalFieldType.Date):
        return timedelta(days=1)
    # numeric open-ended fallback
    return 1_000_000


def iterate_date_windows(
    *,
    get_connection: Callable[[], psycopg.Connection],
    build_windowed_query: Callable[[Any, Any], sql.Composed],
    schema: str,
    table_name: str,
    incremental_field: str,
    incremental_field_type: IncrementalFieldType,
    db_incremental_field_last_value: Any,
    child_partitions: list[ChildPartition],
    chunk_size: int,
    arrow_schema: pa.Schema,
    logger: FilteringBoundLogger,
    initial_window: timedelta | int | float | None = None,
    max_window_multiplier: int = 30,
    min_window_divisor: int = 10,
    using_read_replica: bool = False,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> Iterator[pa.Table]:
    """Walk the incremental field in adaptive bounded windows.

    Each window is a bounded `WHERE incr > lo AND incr <= hi ORDER BY incr ASC`
    query, scoped to one short-lived connection + named (server-side) cursor.
    Adaptive sizing reacts to elapsed wall-clock time (not statement_timeout
    firing): slow windows halve, fast empty windows double. Retry budgets
    bound QueryCanceled and SerializationFailure (read replica) blast radius.
    """
    range_bounds: list[tuple[Any, Any]] = [
        b for b in (partition_bounds_for_range(c, incremental_field_type) for c in child_partitions) if b is not None
    ]

    cursor_lo: Any = db_incremental_field_last_value
    if cursor_lo is None:
        cursor_lo = incremental_type_to_initial_value(incremental_field_type)
    cursor_lo = _ensure_aware(cursor_lo, incremental_field_type)

    if range_bounds:
        min_partition_lo = min(lo_ for lo_, _ in range_bounds)
        # If the pipeline cursor sits below the first partition's lower bound we
        # snap forward to skip the epoch gap. Partition FROM bounds are inclusive
        # but our `WHERE x > lo` filter is exclusive — step back one unit so the
        # first window still captures rows at exactly min_partition_lo.
        if cursor_lo is None or cursor_lo < min_partition_lo:
            lo: Any = _step_back_one(min_partition_lo, incremental_field_type)
        else:
            lo = cursor_lo
    else:
        lo = cursor_lo

    window = _window_default(initial_window, range_bounds, incremental_field_type)
    max_window = window * max_window_multiplier
    min_window = window / min_window_divisor if isinstance(window, timedelta) else max(1, window // min_window_divisor)
    if isinstance(window, timedelta) and min_window == timedelta(0):
        min_window = timedelta(microseconds=1)

    upper = derive_upper_bound(incremental_field_type, range_bounds)

    total_rows = 0
    empty_streak = 0
    qc_retries = 0
    sf_retries = 0
    windows_run = 0
    start = clock()

    logger.info(
        f"iterate_date_windows start: table={schema}.{table_name} field={incremental_field} "
        f"lo={lo} upper={upper} initial_window={window} range_partitions={len(range_bounds)}"
    )

    while upper is None or lo < upper:
        hi = lo + window if upper is None else min(lo + window, upper)
        w_start = clock()
        rows_this_window = 0
        try:
            with get_connection() as conn:
                with conn.cursor(name=f"posthog_win_{schema}_{table_name}_{windows_run}") as cur:
                    query = build_windowed_query(lo, hi)
                    logger.debug(f"window query lo={lo} hi={hi}: {query.as_string()}")
                    cur.execute(query)
                    columns = [c.name for c in cur.description or []]
                    while True:
                        rows = cur.fetchmany(chunk_size)
                        if not rows:
                            break
                        rows_this_window += len(rows)
                        yield table_from_iterator((dict(zip(columns, r)) for r in rows), arrow_schema)
        except psycopg.errors.QueryCanceled:
            qc_retries += 1
            if qc_retries > WINDOW_MAX_QUERY_CANCELED_RETRIES or window <= min_window:
                logger.exception(
                    f"iterate_date_windows: exhausted QueryCanceled retries at lo={lo} hi={hi} window={window}"
                )
                raise QueryTimeoutException(
                    f"window {lo}..{hi} hit statement_timeout after {qc_retries} retries. "
                    f"Please ensure {incremental_field} has an appropriate index."
                )
            window = _halve(window, min_window)
            logger.warning(
                f"iterate_date_windows: QueryCanceled at lo={lo} hi={hi}, "
                f"shrinking window to {window} (retry {qc_retries})"
            )
            continue
        except psycopg.errors.SerializationFailure as e:
            if not (using_read_replica and "conflict with recovery" in "".join(e.args)):
                raise
            sf_retries += 1
            if sf_retries > WINDOW_MAX_SERIALIZATION_RETRIES:
                logger.exception(f"iterate_date_windows: exhausted SerializationFailure retries at lo={lo} hi={hi}")
                raise
            logger.warning(
                f"iterate_date_windows: SerializationFailure at lo={lo} hi={hi} (retry {sf_retries}), backing off"
            )
            sleeper(2 * sf_retries)
            continue

        elapsed = clock() - w_start
        total_rows += rows_this_window
        windows_run += 1
        qc_retries = 0
        sf_retries = 0
        logger.info(
            f"iterate_date_windows: window {lo}..{hi} done: {rows_this_window} rows in {elapsed:.1f}s (window={window})"
        )

        # adaptive sizing on elapsed wall-clock + row volume
        if elapsed < 30 and rows_this_window < chunk_size:
            window = _double(window, max_window)
        elif elapsed > 60:
            window = _halve(window, min_window)

        if upper is None:
            empty_streak = empty_streak + 1 if rows_this_window == 0 else 0
            if empty_streak >= 2:
                logger.info("iterate_date_windows: two consecutive empty windows, terminating open-ended walk")
                break

        lo = hi

    logger.info(
        f"iterate_date_windows complete: {total_rows} rows over {windows_run} windows in {clock() - start:.1f}s"
    )


def iterate_partitions(
    *,
    get_connection: Callable[[], psycopg.Connection],
    build_partition_query: Callable[[str, str], sql.Composed],
    schema: str,
    table_name: str,
    child_partitions: list[ChildPartition],
    chunk_size: int,
    arrow_schema: pa.Schema,
    logger: FilteringBoundLogger,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    db_incremental_field_last_value: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[pa.Table]:
    """One query per child partition. Used when partition key is not the incremental
    field or when the field isn't ordered (string/uuid)."""
    total_rows = 0
    start = clock()

    # If range-partitioned on the incremental field, skip children whose upper
    # bound is at or below cursor to avoid reading already-synced data.
    skippable_upper: Any = db_incremental_field_last_value
    partition_bounds: dict[str, tuple[Any, Any] | None] = {}
    if incremental_field_type is not None and skippable_upper is not None:
        for child in child_partitions:
            partition_bounds[child.name] = partition_bounds_for_range(child, incremental_field_type)

    for child in child_partitions:
        bounds = partition_bounds.get(child.name)
        if bounds is not None and skippable_upper is not None and bounds[1] <= skippable_upper:
            logger.debug(
                f"iterate_partitions: skipping {child.schema}.{child.name} "
                f"(upper {bounds[1]} <= cursor {skippable_upper})"
            )
            continue

        p_start = clock()
        rows_this_partition = 0
        with get_connection() as conn:
            with conn.cursor(name=f"posthog_part_{child.schema}_{child.name}") as cur:
                query = build_partition_query(child.schema, child.name)
                logger.debug(f"partition query {child.schema}.{child.name}: {query.as_string()}")
                cur.execute(query)
                columns = [c.name for c in cur.description or []]
                while True:
                    rows = cur.fetchmany(chunk_size)
                    if not rows:
                        break
                    rows_this_partition += len(rows)
                    yield table_from_iterator((dict(zip(columns, r)) for r in rows), arrow_schema)

        elapsed = clock() - p_start
        total_rows += rows_this_partition
        logger.info(
            f"iterate_partitions: {child.schema}.{child.name} done: {rows_this_partition} rows in {elapsed:.1f}s"
        )

    logger.info(
        f"iterate_partitions complete: {total_rows} rows over {len(child_partitions)} partitions "
        f"in {clock() - start:.1f}s"
    )


def _ensure_aware(value: Any, field_type: IncrementalFieldType) -> Any:
    """Coerce naive DateTime/Timestamp values to UTC-aware so comparisons with
    catalog-parsed partition bounds (which are always aware) don't fail with
    `can't compare offset-naive and offset-aware datetimes`."""
    if field_type not in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp):
        return value
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _step_back_one(value: Any, field_type: IncrementalFieldType) -> Any:
    """Return value - one step of the smallest unit for this type.

    Used when snapping lo forward to a partition lower bound; the exclusive `> lo`
    filter must stand one step behind the inclusive partition FROM bound so the
    first window captures rows sitting exactly on the boundary.
    """
    if field_type == IncrementalFieldType.Date:
        return value - timedelta(days=1)
    if field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp):
        return value - timedelta(microseconds=1)
    # Integer / Numeric
    return value - 1


def _halve(window: Any, floor: Any) -> Any:
    if isinstance(window, timedelta):
        halved = window / 2
        return max(halved, floor)
    return max(window // 2, floor)


def _double(window: Any, cap: Any) -> Any:
    if isinstance(window, timedelta):
        return min(window * 2, cap)
    return min(window * 2, cap)


def is_supported_incremental_type_for_window(field_type: Optional[IncrementalFieldType]) -> bool:
    return field_type is not None and field_type in _DATE_OR_NUMERIC_INCREMENTAL_TYPES


__all__ = [
    "PARTITIONED_TABLE_MAX_CHUNK_SIZE",
    "WINDOW_MAX_QUERY_CANCELED_RETRIES",
    "WINDOW_MAX_SERIALIZATION_RETRIES",
    "ChildPartition",
    "PartitionStrategy",
    "derive_upper_bound",
    "get_estimated_row_count_for_partitioned_table",
    "get_partition_settings_for_partitioned_table",
    "get_partition_strategy",
    "is_partitioned_table",
    "is_supported_incremental_type_for_window",
    "iterate_date_windows",
    "iterate_partitions",
    "list_child_partitions",
    "partition_bounds_for_range",
    "should_preserve_asc_sort",
]
