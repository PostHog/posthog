from __future__ import annotations

import re
import ssl
import math
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any, Literal, Optional

import pyarrow as pa
import structlog
from clickhouse_connect import get_client
from clickhouse_connect.driver.client import Client as ClickHouseClient
from clickhouse_connect.driver.exceptions import ClickHouseError
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    build_pyarrow_decimal_type,
)
from posthog.temporal.data_imports.sources.common.sql import Column, Table

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings

# ClickHouse default ports
CLICKHOUSE_HTTP_PORT = 8123
CLICKHOUSE_HTTPS_PORT = 8443

# Connect timeout for the HTTP client
CONNECT_TIMEOUT_SECONDS = 15
# Per-query timeout for metadata/discovery queries
METADATA_QUERY_TIMEOUT_SECONDS = 30
# Per-query timeout for the main data extraction query
DATA_QUERY_TIMEOUT_SECONDS = 60 * 60  # 1 hour

# Batch accumulation targets for streaming to Delta Lake. ClickHouse yields
# one Arrow block per `max_block_size` rows (20k default); writing each to
# Delta unchanged produces one commit per block, which murders large-table
# performance. We accumulate blocks until we hit either target, then
# concat and yield a single pa.Table to the pipeline.
YIELD_TARGET_BYTES = 200 * 1024 * 1024  # 200 MiB, matches pipeline partition target
YIELD_TARGET_ROWS = 100_000


class ClickHouseConnectionError(Exception):
    """Raised when we cannot establish or use a ClickHouse connection."""

    pass


def _quote_identifier(identifier: str) -> str:
    """Quote a ClickHouse identifier with backticks.

    ClickHouse allows arbitrary identifiers when wrapped in backticks. We
    escape backticks inside the name and refuse identifiers containing
    null bytes — both of which would be unusable in any sane schema.
    """
    if "\x00" in identifier:
        raise ValueError(f"identifier contains null byte: {identifier!r}")
    escaped = identifier.replace("`", "``")
    return f"`{escaped}`"


def _qualified_table(database: str, table_name: str) -> str:
    return f"{_quote_identifier(database)}.{_quote_identifier(table_name)}"


def _get_client(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    query_timeout: int = DATA_QUERY_TIMEOUT_SECONDS,
    settings: Optional[dict[str, Any]] = None,
) -> ClickHouseClient:
    """Create a ClickHouse HTTP client.

    Uses clickhouse-connect, which speaks the HTTP/HTTPS interface. This is
    firewall-friendly, easy to tunnel via SSH, and exposes a streaming Arrow
    reader that we use to read very large tables without buffering them in
    memory.
    """
    try:
        return get_client(
            host=host,
            port=port,
            database=database,
            username=user,
            # clickhouse-connect expects str; passwordless auth is empty string.
            password=password or "",
            secure=secure,
            verify=verify,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            send_receive_timeout=query_timeout,
            query_limit=0,  # we manage limits ourselves
            settings=settings or {},
            compress=True,
        )
    except (ClickHouseError, OSError, ssl.SSLError) as e:
        # OSError covers socket.gaierror, ConnectionRefusedError, TimeoutError,
        # and httpx-raised network errors that subclass OSError. ssl.SSLError
        # covers TLS handshake failures that happen before ClickHouse sees
        # the request.
        raise ClickHouseConnectionError(str(e)) from e


def _strip_type_modifiers(type_name: str) -> tuple[str, bool]:
    """Strip Nullable(...) and LowCardinality(...) wrappers.

    Returns the inner type and whether the original type was Nullable.
    LowCardinality alone does not affect nullability, so we recursively
    unwrap it but never set the nullable flag for it.
    """
    nullable = False
    current = type_name.strip()

    while True:
        if current.startswith("Nullable(") and current.endswith(")"):
            nullable = True
            current = current[len("Nullable(") : -1].strip()
        elif current.startswith("LowCardinality(") and current.endswith(")"):
            current = current[len("LowCardinality(") : -1].strip()
        else:
            break

    return current, nullable


def filter_clickhouse_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Return columns suitable for use as an incremental cursor.

    ClickHouse type names are case-sensitive in metadata responses (e.g.
    `DateTime64(6)`, `Int64`, `Date`). We unwrap Nullable/LowCardinality
    wrappers first and then match against the bare type.
    """
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, raw_type, nullable in columns:
        inner_type, _ = _strip_type_modifiers(raw_type)
        # DateTime, DateTime64, DateTime('UTC'), DateTime64(3, 'UTC'), ...
        if inner_type.startswith("DateTime"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif inner_type in ("Date", "Date32"):
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif inner_type in (
            "Int8",
            "Int16",
            "Int32",
            "Int64",
            "Int128",
            "Int256",
            "UInt8",
            "UInt16",
            "UInt32",
            "UInt64",
            "UInt128",
            "UInt256",
        ):
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def get_schemas(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, bool]]]:
    """Discover columns for all tables in the given database.

    Uses `system.columns`, which gives us everything in one round trip.
    Note: ClickHouse columns expose the *original* type string, including
    Nullable/LowCardinality wrappers — we keep the wrappers and parse them
    later, so we can preserve nullability information.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
    )

    try:
        params: dict[str, Any] = {"database": database}
        names_filter = ""
        if names:
            # clickhouse-connect formats tuples as `(a, b, c)`, which matches
            # ClickHouse's IN clause syntax. Lists would format as `[a, b, c]`
            # which is valid but less standard.
            params["names"] = tuple(names)
            names_filter = "AND table IN %(names)s"

        result = client.query(
            f"""
            SELECT table, name, type
            FROM system.columns
            WHERE database = %(database)s {names_filter}
            ORDER BY table ASC, position ASC
            """,
            parameters=params,
        )
    finally:
        client.close()

    schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
    for row in result.result_rows:
        table_name, column_name, raw_type = row[0], row[1], row[2]
        _, nullable = _strip_type_modifiers(raw_type)
        schema_list[table_name].append((column_name, raw_type, nullable))

    return schema_list


# Match `TO db.table` or `TO table` clause in MV CREATE statement.
# ClickHouse always emits the target in `system.tables.create_table_query`
# for MVs created with explicit `TO` target.
_MV_TO_TARGET_RE = re.compile(
    r"\bTO\s+(?:`((?:[^`]|``)+)`|(\w+))(?:\.(?:`((?:[^`]|``)+)`|(\w+)))?",
    re.IGNORECASE,
)


def _parse_mv_target(create_query: str | None) -> tuple[str, str] | None:
    """Parse (database, table) target from an MV's CREATE statement.

    Only matches `TO <target>` — not `AS SELECT ... FROM <source>`. If the
    MV has no explicit target, returns None and the caller uses the
    `.inner_id.<uuid>` lookup instead.
    """
    if not create_query:
        return None
    match = _MV_TO_TARGET_RE.search(create_query)
    if match is None:
        return None
    first = (match.group(1) or match.group(2) or "").replace("``", "`")
    second = (match.group(3) or match.group(4) or "").replace("``", "`")
    if second:
        return (first, second)
    # Single identifier means `TO target` without database qualifier — we
    # can't resolve this without knowing the MV's own database; caller
    # passes it in.
    return ("", first)


def get_clickhouse_row_count(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    names: list[str] | None = None,
) -> dict[str, int]:
    """Return total_rows per table from `system.tables`.

    Coverage:
    - MergeTree family: free — ClickHouse keeps a running counter.
    - Distributed: fall back to `SELECT count()` (cheap, distributed).
    - MaterializedView with `TO target`: resolve target, use its total_rows.
    - MaterializedView without TO: resolve `.inner_id.<uuid>` inner table.
    - Plain View / LiveView / WindowView / Memory / Buffer / Log / Kafka /
      URL etc: omitted — count would require executing the view or scanning
      the whole table.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
    )

    try:
        params: dict[str, Any] = {"database": database}
        names_filter = ""
        if names:
            params["names"] = tuple(names)
            names_filter = "AND name IN %(names)s"

        result = client.query(
            f"""
            SELECT name, total_rows, engine, uuid, create_table_query
            FROM system.tables
            WHERE database = %(database)s {names_filter}
            """,
            parameters=params,
        )

        counts: dict[str, int] = {}
        distributed_fallbacks: list[str] = []
        mv_targets: dict[str, tuple[str, str]] = {}  # mv_name -> (target_db, target_table)
        mv_inner_lookups: dict[str, str] = {}  # mv_name -> uuid (for .inner_id.<uuid>)

        for row in result.result_rows:
            name, total_rows, engine, uuid_val, create_query = row[0], row[1], row[2], row[3], row[4]
            if total_rows is not None:
                counts[name] = int(total_rows)
                continue
            if engine == "Distributed":
                distributed_fallbacks.append(name)
                continue
            if engine == "MaterializedView":
                target = _parse_mv_target(create_query)
                if target is not None:
                    target_db, target_table = target
                    mv_targets[name] = (target_db or database, target_table)
                elif uuid_val:
                    mv_inner_lookups[name] = str(uuid_val)

        for name in distributed_fallbacks:
            try:
                count_result = client.query(f"SELECT count() FROM {_qualified_table(database, name)}")
                if count_result.result_rows and count_result.result_rows[0][0] is not None:
                    counts[name] = int(count_result.result_rows[0][0])
            except ClickHouseError:
                continue

        # Batch lookup MV targets' total_rows via system.tables.
        if mv_targets:
            target_keys = list({(db, tbl) for db, tbl in mv_targets.values()})
            try:
                target_result = client.query(
                    """
                    SELECT database, name, total_rows
                    FROM system.tables
                    WHERE (database, name) IN %(keys)s AND total_rows IS NOT NULL
                    """,
                    parameters={"keys": tuple(target_keys)},
                )
                target_counts = {(row[0], row[1]): int(row[2]) for row in target_result.result_rows}
                for mv_name, (target_db, target_table) in mv_targets.items():
                    target_count = target_counts.get((target_db, target_table))
                    if target_count is not None:
                        counts[mv_name] = target_count
            except ClickHouseError:
                pass

        # Batch lookup MVs without TO target via .inner_id.<uuid>.
        if mv_inner_lookups:
            inner_names = tuple(f".inner_id.{uuid}" for uuid in mv_inner_lookups.values())
            try:
                inner_result = client.query(
                    """
                    SELECT name, total_rows
                    FROM system.tables
                    WHERE database = %(database)s AND name IN %(names)s AND total_rows IS NOT NULL
                    """,
                    parameters={"database": database, "names": inner_names},
                )
                inner_counts = {row[0]: int(row[1]) for row in inner_result.result_rows}
                for mv_name, uuid in mv_inner_lookups.items():
                    inner_count = inner_counts.get(f".inner_id.{uuid}")
                    if inner_count is not None:
                        counts[mv_name] = inner_count
            except ClickHouseError:
                pass
    except ClickHouseError:
        return {}
    finally:
        client.close()

    return counts


def get_connection_metadata(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
) -> dict[str, Any]:
    """Probe the server for version metadata.

    Used during onboarding to surface a sensible error if credentials are
    valid but the database doesn't exist, and to record server version on
    the source for future debugging.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
    )

    try:
        result = client.query("SELECT version(), currentDatabase()")
        row = result.result_rows[0] if result.result_rows else (None, None)
        version = str(row[0]) if row[0] is not None else ""
        current_database = str(row[1]) if row[1] is not None else database

        return {
            "database": current_database,
            "version": version,
            "engine": "clickhouse",
        }
    finally:
        client.close()


# Regex helpers for parsing ClickHouse type strings.
# DecimalN(S) variants have fixed precision implied by N — the single
# argument is scale, not precision. Decimal(P, S) / Decimal(P) is the
# explicit form.
_DECIMAL_FIXED_WIDTHS: dict[str, int] = {"32": 9, "64": 18, "128": 38, "256": 76}
_DECIMAL_FIXED_RE = re.compile(r"^Decimal(32|64|128|256)\(\s*(\d+)\s*\)$")
_DECIMAL_VAR_RE = re.compile(r"^Decimal\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)$")
_DATETIME64_RE = re.compile(r"^DateTime64\(\s*(\d+)\s*(?:,\s*'([^']*)'\s*)?\)$")
_DATETIME_RE = re.compile(r"^DateTime(?:\(\s*'([^']*)'\s*\))?$")
_FIXED_STRING_RE = re.compile(r"^FixedString\(\s*\d+\s*\)$")
_ENUM_RE = re.compile(r"^Enum(?:8|16)\(.*\)$")


def _datetime_unit_for_precision(precision: int) -> Literal["s", "ms", "us", "ns"]:
    if precision <= 0:
        return "s"
    if precision <= 3:
        return "ms"
    if precision <= 6:
        return "us"
    return "ns"


class ClickHouseColumn(Column):
    """Implementation of the `Column` protocol for a ClickHouse source.

    Attributes:
        name: The column's name.
        data_type: The original ClickHouse type string, possibly wrapped in
            `Nullable(...)` and/or `LowCardinality(...)`.
        nullable: Whether the column is nullable. Derived from the
            `Nullable(...)` wrapper.
    """

    def __init__(self, name: str, data_type: str, nullable: bool) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        inner, _ = _strip_type_modifiers(self.data_type)
        arrow_type = self._inner_to_arrow_type(inner)
        return pa.field(self.name, arrow_type, nullable=self.nullable)

    @classmethod
    def _inner_to_arrow_type(cls, inner: str) -> pa.DataType:
        # Integer types
        match inner:
            case "Int8":
                return pa.int8()
            case "Int16":
                return pa.int16()
            case "Int32":
                return pa.int32()
            case "Int64":
                return pa.int64()
            case "UInt8":
                return pa.uint8()
            case "UInt16":
                return pa.uint16()
            case "UInt32":
                return pa.uint32()
            case "UInt64":
                return pa.uint64()
            case "Float32":
                return pa.float32()
            case "Float64":
                return pa.float64()
            case "Bool":
                return pa.bool_()
            case "String":
                return pa.string()
            case "UUID":
                return pa.string()
            case "Date":
                return pa.date32()
            case "Date32":
                return pa.date32()
            case "IPv4" | "IPv6":
                return pa.string()
            # Wide integers we cannot represent natively in Arrow — fall back to
            # string so we don't silently truncate.
            case "Int128" | "Int256" | "UInt128" | "UInt256":
                return pa.string()

        # DateTime / DateTime('UTC')
        match_dt = _DATETIME_RE.match(inner)
        if match_dt is not None:
            # pa.timestamp stubs don't accept tz=None as a typed overload, so
            # we branch instead of passing through Optional[str].
            tz = match_dt.group(1) or None
            return pa.timestamp("s", tz=tz) if tz else pa.timestamp("s")

        # DateTime64(precision[, timezone])
        match_dt64 = _DATETIME64_RE.match(inner)
        if match_dt64 is not None:
            precision = int(match_dt64.group(1))
            tz = match_dt64.group(2) or None
            unit = _datetime_unit_for_precision(precision)
            return pa.timestamp(unit, tz=tz) if tz else pa.timestamp(unit)

        # DecimalN(S) — N fixes precision (9/18/38/76), the lone arg is scale.
        match_fixed = _DECIMAL_FIXED_RE.match(inner)
        if match_fixed is not None:
            precision = _DECIMAL_FIXED_WIDTHS[match_fixed.group(1)]
            scale = int(match_fixed.group(2))
            return build_pyarrow_decimal_type(precision, scale)

        # Decimal(P[, S]) — explicit precision and scale.
        match_dec = _DECIMAL_VAR_RE.match(inner)
        if match_dec is not None:
            precision = int(match_dec.group(1))
            scale = int(match_dec.group(2)) if match_dec.group(2) is not None else 0
            return build_pyarrow_decimal_type(precision, scale)

        # FixedString(N) — bytes-like, but stored as string for portability
        if _FIXED_STRING_RE.match(inner):
            return pa.string()

        # Enum8(...) / Enum16(...) — surface labels as strings
        if _ENUM_RE.match(inner):
            return pa.string()

        # Composite types — Array, Map, Tuple, Nested, JSON, Object — are
        # serialized to a JSON string. We could be smarter about Array of
        # primitives in the future.
        if (
            inner.startswith("Array(")
            or inner.startswith("Map(")
            or inner.startswith("Tuple(")
            or inner.startswith("Nested(")
            or inner.startswith("Variant(")
            or inner.startswith("Dynamic")
            or inner.startswith("JSON")
            or inner.startswith("Object(")
        ):
            return pa.string()

        # Anything we don't recognise is safest as a string.
        return pa.string()


def _is_view_engine(engine: str | None) -> bool:
    if not engine:
        return False
    return engine in ("View", "MaterializedView", "LiveView", "WindowView")


def _is_materialized_view_engine(engine: str | None) -> bool:
    return engine == "MaterializedView"


def _get_table(client: ClickHouseClient, database: str, table_name: str) -> Table[ClickHouseColumn]:
    """Read columns + table type for a single table from system tables."""
    cols_result = client.query(
        """
        SELECT name, type
        FROM system.columns
        WHERE database = %(database)s AND table = %(table)s
        ORDER BY position ASC
        """,
        parameters={"database": database, "table": table_name},
    )

    columns: list[ClickHouseColumn] = []
    for name, raw_type in cols_result.result_rows:
        _, nullable = _strip_type_modifiers(raw_type)
        columns.append(ClickHouseColumn(name=name, data_type=raw_type, nullable=nullable))

    if not columns:
        raise ValueError(f"Table {database}.{table_name} not found or has no columns")

    engine_result = client.query(
        "SELECT engine FROM system.tables WHERE database = %(database)s AND name = %(table)s",
        parameters={"database": database, "table": table_name},
    )
    engine = engine_result.result_rows[0][0] if engine_result.result_rows else None

    table_type: str = "table"
    if _is_materialized_view_engine(engine):
        table_type = "materialized_view"
    elif _is_view_engine(engine):
        table_type = "view"

    return Table(name=table_name, parents=(database,), columns=columns, type=table_type)  # type: ignore[arg-type]


def _get_primary_keys(client: ClickHouseClient, database: str, table_name: str) -> list[str] | None:
    """Return the columns of the table's sorting key.

    ClickHouse's primary key is by definition a prefix of the sorting key,
    and is the closest analog to a unique key — though it is *not*
    necessarily unique. Callers must be prepared to handle duplicates.
    """
    result = client.query(
        """
        SELECT name
        FROM system.columns
        WHERE database = %(database)s AND table = %(table)s AND is_in_sorting_key = 1
        ORDER BY position ASC
        """,
        parameters={"database": database, "table": table_name},
    )
    keys = [row[0] for row in result.result_rows]
    return keys if keys else None


def get_primary_keys_for_schemas(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    table_names: list[str],
) -> dict[str, list[str] | None]:
    """Detect primary keys (sorting key columns) for multiple tables.

    Opens a single client and reuses `_get_primary_keys` per table. Returns
    a dict keyed by every input table name, with None for tables where no
    sorting key exists or the lookup failed.
    """
    result: dict[str, list[str] | None] = dict.fromkeys(table_names)
    if not table_names:
        return result

    try:
        client = _get_client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            secure=secure,
            verify=verify,
            query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
        )
        try:
            for table_name in table_names:
                try:
                    result[table_name] = _get_primary_keys(client, database, table_name)
                except ClickHouseError as e:
                    structlog.get_logger().warning(
                        "Failed to detect primary keys for ClickHouse table",
                        table=table_name,
                        exc_info=e,
                    )
        finally:
            client.close()
    except Exception as e:
        structlog.get_logger().warning("Failed to detect primary keys for ClickHouse schemas", exc_info=e)

    return result


# Row budget for the duplicate-PK probe. ClickHouse sorting keys are not
# enforced unique, so we need *some* signal before trusting a user-selected
# key for incremental merges — but a full-table GROUP BY (even streamed in
# sort-key order) is too expensive to run every sync on billion-row tables.
# Instead we scan up to this many rows and trust the user if no duplicate
# surfaces. Misconfigured sort keys overwhelmingly surface duplicates in
# any reasonably-sized prefix.
DUPLICATE_PK_CHECK_ROW_BUDGET = 10_000_000

# Settings for the duplicate-PK probe.
# - optimize_aggregation_in_order streams the GROUP BY along the sorting
#   key without building a hash table (bounded memory).
# - max_rows_to_read + read_overflow_mode='break' cap the scan at
#   DUPLICATE_PK_CHECK_ROW_BUDGET and *silently stop* instead of throwing.
# - max_execution_time and max_memory_usage are belt-and-braces bounds.
_DUPLICATE_PK_CHECK_SETTINGS: dict[str, Any] = {
    "optimize_aggregation_in_order": 1,
    "max_rows_to_read": DUPLICATE_PK_CHECK_ROW_BUDGET,
    "read_overflow_mode": "break",
    "max_execution_time": 30,
    "max_memory_usage": 1_000_000_000,
}


def _has_duplicate_primary_keys(
    client: ClickHouseClient,
    database: str,
    table_name: str,
    primary_keys: list[str] | None,
    logger: FilteringBoundLogger,
) -> bool:
    """Check whether the sorting key has obvious duplicate combinations.

    ClickHouse sorting keys are *not* enforced unique. For incremental syncs
    we need a unique-ish key to do safe merges into Delta. We probe a
    bounded prefix of the table (DUPLICATE_PK_CHECK_ROW_BUDGET rows) rather
    than scanning the whole thing, because:

    1. A user who chose a non-unique sort key will virtually always show
       duplicates inside any reasonably sized prefix.
    2. A full-table GROUP BY every incremental sync is prohibitively
       expensive on the tables this source is designed for.
    3. ClickHouse cannot *prove* uniqueness anyway — only the user can.

    Returns:
        True if duplicates are detected in the probed prefix, or if the
        probe failed in an unexpected way. False when the probe completed
        within budget without finding duplicates.
    """
    if not primary_keys:
        return False

    quoted_keys = ", ".join(_quote_identifier(k) for k in primary_keys)
    # LIMIT 1 lets ClickHouse short-circuit the moment it finds a duplicate.
    query = f"SELECT 1 FROM {_qualified_table(database, table_name)} GROUP BY {quoted_keys} HAVING count() > 1 LIMIT 1"
    try:
        result = client.query(query, settings=_DUPLICATE_PK_CHECK_SETTINGS)
        return len(result.result_rows) > 0
    except ClickHouseError as e:
        # Any unexpected server error is treated as "assume duplicates" —
        # safer to force append mode than to merge against a key we couldn't
        # verify. (We don't hit max_rows_to_read here because
        # read_overflow_mode='break' turns that into a silent truncation.)
        logger.warning(
            f"_has_duplicate_primary_keys: assuming duplicates exist (probe failed for {database}.{table_name}): {e}"
        )
        capture_exception(e)
        return True


def _get_incremental_row_count(
    client: ClickHouseClient,
    database: str,
    table_name: str,
    incremental_field: str,
    last_value: Any,
    logger: FilteringBoundLogger,
) -> int | None:
    """Count rows the incremental sync will actually pull.

    `system.tables.total_rows` is the size of the entire table, which
    overstates the work for incremental syncs after the initial backfill.
    This query is cheap when the cursor is in the sorting key (primary
    index skip). On error or timeout we return None and the caller falls
    back to the total-table count.
    """
    quoted_field = _quote_identifier(incremental_field)
    query = f"SELECT count() FROM {_qualified_table(database, table_name)} WHERE {quoted_field} > %(last_value)s"
    try:
        result = client.query(
            query,
            parameters={"last_value": last_value},
            settings={"max_execution_time": 30},
        )
    except ClickHouseError as e:
        logger.debug(f"_get_incremental_row_count: fell back, count query failed: {e}")
        return None

    if not result.result_rows:
        return None
    count = result.result_rows[0][0]
    return int(count) if count is not None else None


def _get_partition_settings(
    client: ClickHouseClient, database: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    """Compute partition settings using `system.tables.total_bytes`.

    ClickHouse maintains compressed and uncompressed sizes per table — we
    use total_bytes (compressed on disk) as a rough proxy for memory cost
    on the pipeline side. For non-MergeTree engines `total_bytes` may be
    NULL, in which case we return None and the pipeline falls back to its
    default partitioning.
    """
    try:
        result = client.query(
            """
            SELECT total_rows, total_bytes
            FROM system.tables
            WHERE database = %(database)s AND name = %(table)s
            """,
            parameters={"database": database, "table": table_name},
        )
    except ClickHouseError as e:
        capture_exception(e)
        logger.debug(f"_get_partition_settings: failed: {e}")
        return None

    if not result.result_rows:
        return None

    total_rows, total_bytes = result.result_rows[0]
    if total_rows is None or total_bytes is None or total_rows == 0 or total_bytes == 0:
        return None

    bytes_per_row = total_bytes / total_rows
    if bytes_per_row <= 0:
        return None

    partition_size = max(1, int(round(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / bytes_per_row)))
    partition_count = max(1, math.floor(total_rows / partition_size))

    logger.debug(
        f"_get_partition_settings: total_rows={total_rows} total_bytes={total_bytes} "
        f"partition_size={partition_size} partition_count={partition_count}"
    )
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


# ClickHouse types Arrow output can't emit directly — we coerce to String
# via toString() to avoid ClickHouse error 50 "Type is not supported by Arrow".
_ARROW_UNSUPPORTED_EXACT = frozenset(
    {
        "UUID",
        "IPv4",
        "IPv6",
        "Int128",
        "Int256",
        "UInt128",
        "UInt256",
        "Dynamic",
        "JSON",
    }
)
_ARROW_UNSUPPORTED_PREFIXES: tuple[str, ...] = (
    "Enum8(",
    "Enum16(",
    "FixedString(",
    "Array(",
    "Map(",
    "Tuple(",
    "Nested(",
    "Variant(",
    "Object(",
)


def _needs_to_string_cast(inner: str) -> bool:
    if inner in _ARROW_UNSUPPORTED_EXACT:
        return True
    return any(inner.startswith(prefix) for prefix in _ARROW_UNSUPPORTED_PREFIXES)


def _build_select_list(columns: list[ClickHouseColumn]) -> str:
    """Build explicit SELECT list, wrapping Arrow-unsupported types in toString()."""
    parts: list[str] = []
    for col in columns:
        quoted = _quote_identifier(col.name)
        inner, _ = _strip_type_modifiers(col.data_type)
        if _needs_to_string_cast(inner):
            parts.append(f"toString({quoted}) AS {quoted}")
        else:
            parts.append(quoted)
    return ", ".join(parts)


def _build_query(
    *,
    database: str,
    table_name: str,
    columns: list[ClickHouseColumn],
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> str:
    """Build the data extraction query.

    Returns the SQL string. We never interpolate the incremental cursor
    value directly — only identifiers (which are validated) end up in the
    SQL string. Column types ClickHouse can't emit as Arrow (UUID, IPv4,
    enums, arrays, ...) are wrapped in toString() to avoid error 50.
    """
    qualified = _qualified_table(database, table_name)
    select_list = _build_select_list(columns)

    if not should_use_incremental_field:
        return f"SELECT {select_list} FROM {qualified}"

    if incremental_field is None:
        raise ValueError("incremental_field can't be None when should_use_incremental_field is True")

    quoted_field = _quote_identifier(incremental_field)
    return f"SELECT {select_list} FROM {qualified} WHERE {quoted_field} > %(last_value)s ORDER BY {quoted_field} ASC"


def _query_settings(chunk_size: int) -> dict[str, Any]:
    """ClickHouse server-side settings applied to every data query.

    These tune the streaming Arrow output and prevent runaway resource use
    on the source side. They are intentionally conservative — operators
    can override per-source via chunk_size_override on the schema.
    """
    return {
        # Stream Arrow record batches in chunks of `chunk_size` rows. This is
        # the per-batch row limit on the source side and bounds memory.
        "max_block_size": chunk_size,
        # Make Arrow output use real String columns instead of binary buffers,
        # which keeps the resulting RecordBatches readable by Delta Lake.
        "output_format_arrow_string_as_string": 1,
        # Materialize LowCardinality columns into their underlying type, so the
        # PyArrow schema we generate matches what we receive.
        "output_format_arrow_low_cardinality_as_dictionary": 0,
        # Cap query execution time to avoid hanging the worker on a runaway
        # source-side query.
        "max_execution_time": DATA_QUERY_TIMEOUT_SECONDS,
        # When the ORDER BY column is a prefix of the sorting key, read parts
        # in sort order and skip the top-level sort entirely. Free when
        # applicable, harmless otherwise. Critical for incremental syncs on
        # big tables — without this, ORDER BY forces a full external sort.
        "optimize_read_in_order": 1,
        # If we still have to sort (cursor not in sorting key), spill to disk
        # at 500 MB instead of OOMing the server. The hot path stays in
        # memory, slow path degrades gracefully.
        "max_bytes_before_external_sort": 500 * 1024 * 1024,
    }


def clickhouse_source(
    *,
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str | None,
    database: str,
    secure: bool,
    verify: bool,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    """Build a SourceResponse that pulls a single ClickHouse table.

    Streams the data via Arrow batches so we never materialize the whole
    table in memory. Each yielded `pa.Table` is one Arrow record batch.
    """
    if not table_names or not table_names[0]:
        raise ValueError("Table name is missing")
    table_name = table_names[0]

    chunk_size = chunk_size_override if chunk_size_override is not None else DEFAULT_CHUNK_SIZE

    with tunnel() as (host, port):
        client = _get_client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            secure=secure,
            verify=verify,
            query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
        )

        try:
            logger.info(f"Discovering table {database}.{table_name}")
            table = _get_table(client, database, table_name)
            logger.info(f"Source schema: {table.to_arrow_schema()}")

            primary_keys = _get_primary_keys(client, database, table_name)
            if primary_keys:
                logger.debug(f"Found primary keys (sorting key): {primary_keys}")

            # Warn when the incremental cursor isn't the sorting-key prefix.
            # ClickHouse can only skip the sort if the ORDER BY column leads
            # the sorting key; otherwise every incremental run does a full
            # server-side sort. `max_bytes_before_external_sort` in
            # `_query_settings` keeps it from OOMing, but it will be slow.
            if should_use_incremental_field and incremental_field and primary_keys:
                if primary_keys[0] != incremental_field:
                    logger.warning(
                        f"Incremental cursor '{incremental_field}' is not the first "
                        f"column of the sorting key {primary_keys} for "
                        f"{database}.{table_name}. Each incremental sync will perform "
                        f"a server-side sort. Consider a cursor that matches the "
                        f"table's sorting key for best performance."
                    )

            row_counts = get_clickhouse_row_count(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                secure=secure,
                verify=verify,
                names=[table_name],
            )
            rows_to_sync: int | None = row_counts.get(table_name)

            # For incremental resumes, pull the filtered count so progress
            # reporting isn't anchored to the full table size.
            if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
                incremental_count = _get_incremental_row_count(
                    client,
                    database,
                    table_name,
                    incremental_field,
                    db_incremental_field_last_value,
                    logger,
                )
                if incremental_count is not None:
                    rows_to_sync = incremental_count

            partition_settings = (
                _get_partition_settings(client, database, table_name, logger) if should_use_incremental_field else None
            )

            has_duplicate_primary_keys = False
            if should_use_incremental_field and primary_keys:
                has_duplicate_primary_keys = _has_duplicate_primary_keys(
                    client, database, table_name, primary_keys, logger
                )
        finally:
            client.close()

    def get_rows() -> Iterator[Any]:
        logger.info(f"get_rows: starting stream for {database}.{table_name} chunk_size={chunk_size}")
        # Open a fresh tunnel + client for the streaming read so the
        # connection used for discovery isn't held open longer than needed.
        with tunnel() as (stream_host, stream_port):
            stream_client = _get_client(
                host=stream_host,
                port=stream_port,
                database=database,
                user=user,
                password=password,
                secure=secure,
                verify=verify,
                query_timeout=DATA_QUERY_TIMEOUT_SECONDS,
                settings=_query_settings(chunk_size),
            )

            try:
                query = _build_query(
                    database=database,
                    table_name=table_name,
                    columns=list(table.columns),
                    should_use_incremental_field=should_use_incremental_field,
                    incremental_field=incremental_field,
                )

                parameters: dict[str, Any] = {}
                if should_use_incremental_field:
                    last_value = db_incremental_field_last_value
                    if last_value is None and incremental_field_type is not None:
                        last_value = incremental_type_to_initial_value(incremental_field_type)
                    parameters["last_value"] = last_value

                logger.info(f"ClickHouse query: {query}")

                # query_arrow_stream yields pa.RecordBatch chunks — one per
                # ClickHouse block, capped by max_block_size. We accumulate
                # these into ~YIELD_TARGET_BYTES / YIELD_TARGET_ROWS pa.Tables
                # before yielding, so the pipeline's Delta writer sees fewer,
                # larger batches and commits fewer Delta files.
                pending: list[pa.RecordBatch] = []
                pending_rows = 0
                pending_bytes = 0
                with stream_client.query_arrow_stream(query, parameters=parameters) as stream:
                    for chunk in stream:
                        if chunk.num_rows == 0:
                            continue
                        pending.append(chunk)
                        pending_rows += chunk.num_rows
                        pending_bytes += chunk.nbytes
                        if pending_rows >= YIELD_TARGET_ROWS or pending_bytes >= YIELD_TARGET_BYTES:
                            yield pa.Table.from_batches(pending)
                            pending = []
                            pending_rows = 0
                            pending_bytes = 0

                if pending:
                    yield pa.Table.from_batches(pending)
            finally:
                stream_client.close()

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
    )
