"""MySQL driver for PostHog's data-warehouse import pipeline.

Everything MySQL-specific — connection lifecycle (with SSH tunnel),
schema listing, per-cursor metadata for the streaming sync, the dlt
pipeline build, type conversions, the `FORCE INDEX` bad-plan fallback —
lives on `MySQLImplementation`. The source-class `MySQLSource` is a
thin PostHog-layer wrapper that just holds an instance and validates
credentials.

Module-level free helpers (`_build_query`, `_sanitize_identifier`,
`_safe_convert_date`, `_safe_convert_datetime`, `_is_bad_plan_timeout`)
are pure functions used by `MySQLImplementation` and exercised directly
by unit tests. They take no MySQL-driver state and are fine as
module-scope primitives.
"""

from __future__ import annotations

import datetime
import collections
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings

import pyarrow as pa
import pymysql
import structlog
import pymysql.converters
from pymysql.constants import FIELD_TYPE
from pymysql.cursors import Cursor, SSCursor
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from posthog.temporal.data_imports.sources.common.sql import (
    BacktickIdentifierQuoter,
    Column,
    InvalidIdentifierError,
    SelectQueryBuilder,
    Table,
)
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation, TableStats
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import MySQLSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType

__all__ = [
    "MySQLColumn",
    "MySQLImplementation",
    "STATEMENT_TIMEOUT_SECONDS",
    "filter_mysql_incremental_fields",
]

_IDENTIFIER_QUOTER = BacktickIdentifierQuoter()
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER)

# Applied to the row-streaming connection so large result preparation
# (e.g. filesort on a multi-GB table) doesn't hit MySQL's default 60s
# net_write_timeout before the first rows are ready. Used for both the
# client-side PyMySQL read_timeout and the server-side SET SESSION
# net_write_timeout / net_read_timeout — PyMySQL and MySQL both take seconds.
STATEMENT_TIMEOUT_SECONDS = 600  # 10 mins

# pymysql error code for "Lost connection to MySQL server during query" — the
# symptom we see when the optimizer picks a bad plan (full scan + filesort) and
# the filesort preparation exceeds a middlebox / server-side query timeout
# before any rows stream back.
_LOST_CONNECTION_DURING_QUERY_CODE = 2013


def _safe_convert_date(obj: Any) -> datetime.date | None:
    """Convert MySQL date, returning None for invalid dates like '0000-00-00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        parts = obj.split("-", 2)
        return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, AttributeError):
        return None


def _safe_convert_datetime(obj: Any) -> datetime.datetime | None:
    """Convert MySQL datetime/timestamp, returning None for invalid values like '0000-00-00 00:00:00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        date_part, time_part = obj.split(" ", 1)
        date_values = [int(x) for x in date_part.split("-", 2)]
        time_parts = time_part.split(":", 2)
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        # Handle optional microseconds
        sec_parts = time_parts[2].split(".", 1)
        seconds = int(sec_parts[0])
        microseconds = int(sec_parts[1].ljust(6, "0")) if len(sec_parts) > 1 else 0
        return datetime.datetime(date_values[0], date_values[1], date_values[2], hours, minutes, seconds, microseconds)
    except (ValueError, IndexError, AttributeError):
        return None


# Custom conversions that return None for MySQL zero dates instead of raw strings
_MYSQL_SAFE_CONVERSIONS: dict[type[object] | int, Any] = {
    **pymysql.converters.conversions,
    FIELD_TYPE.DATE: _safe_convert_date,
    FIELD_TYPE.DATETIME: _safe_convert_datetime,
    FIELD_TYPE.TIMESTAMP: _safe_convert_datetime,
}


def filter_mysql_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type == "tinyint" or type == "smallint" or type == "mediumint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def _sanitize_identifier(identifier: str) -> str:
    """Back-compat shim for callers that still expect a plain `ValueError`.

    New code should use `BacktickIdentifierQuoter` directly — same allowlist,
    same quoting, exposed through the shared `IdentifierQuoter` interface.
    """
    try:
        return _IDENTIFIER_QUOTER.quote(identifier)
    except InvalidIdentifierError as e:
        # Preserve the old message shape so semgrep / log-matching rules that
        # key on the old text keep working.
        raise ValueError(f"Invalid SQL identifier: {identifier}") from e


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    force_index_name: str | None = None,
) -> tuple[str, dict[str, Any]]:
    hint: str | None = None
    if force_index_name is not None:
        # Sanitize before building the hint — bad names must fail fast.
        hint = f"FORCE INDEX ({_IDENTIFIER_QUOTER.quote(force_index_name)})"

    if not should_use_incremental_field:
        result = _QUERY_BUILDER.select_all(
            schema=schema,
            table_name=table_name,
            extra_table_hint=hint,
        )
        params = result.params if isinstance(result.params, dict) else {}
        return result.sql, params

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    result = _QUERY_BUILDER.select_all(
        schema=schema,
        table_name=table_name,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        incremental_last_value=db_incremental_field_last_value,
        extra_table_hint=hint,
    )
    params = result.params if isinstance(result.params, dict) else {}
    return result.sql, params


def _is_bad_plan_timeout(e: pymysql.err.OperationalError) -> bool:
    """Return True if the error suggests we hit a bad-plan-induced query timeout.

    Narrowly matches `OperationalError(2013, ...)`. Other `OperationalError`s
    (access denied, table missing, etc.) should propagate untouched.
    """
    code = e.args[0] if e.args else None
    return code == _LOST_CONNECTION_DURING_QUERY_CODE


class MySQLColumn(Column):
    """`Column` for a MySQL source — carries enough type info to build a PyArrow field.

    Attributes:
        name: Column name.
        data_type: Base MySQL type (`int`, `varchar`, `decimal`, …).
        column_type: Full type string including modifiers (e.g. `int(10) unsigned`),
            used to detect `unsigned` which affects the PyArrow integer width.
        nullable: Whether the column is nullable in MySQL.
        numeric_precision / numeric_scale: Populated only for `decimal` / `numeric`.
    """

    def __init__(
        self,
        name: str,
        data_type: str,
        column_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.column_type = column_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        # deltalake doesn't support unsigned types, so unsigned ints are
        # widened to the next signed type that can hold their range.
        is_unsigned = "unsigned" in self.column_type

        match self.data_type.lower():
            case "bigint":
                # No larger type than (u)int64 — keep unsigned semantics.
                arrow_type = pa.uint64() if is_unsigned else pa.int64()
            case "int" | "integer" | "mediumint":
                arrow_type = pa.uint64() if is_unsigned else pa.int32()
            case "smallint":
                arrow_type = pa.uint32() if is_unsigned else pa.int16()
            case "tinyint":
                arrow_type = pa.uint16() if is_unsigned else pa.int8()
            case "decimal" | "numeric":
                if self.numeric_precision is None or self.numeric_scale is None:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")
                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "float":
                arrow_type = pa.float32()
            case "double" | "double precision":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "mediumtext" | "longtext":
                arrow_type = pa.string()
            case "date":
                # MySQL allows zero dates ('0000-00-00') which we map to None,
                # so date columns must always be nullable in the Arrow schema.
                arrow_type = pa.date32()
                return pa.field(self.name, arrow_type, nullable=True)
            case "datetime" | "timestamp":
                arrow_type = pa.timestamp("us")
                return pa.field(self.name, arrow_type, nullable=True)
            case "time":
                arrow_type = pa.time64("us")
            case "boolean" | "bool":
                arrow_type = pa.bool_()
            case "binary" | "varbinary" | "blob" | "mediumblob" | "longblob":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types (not native in MySQL)
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


class MySQLImplementation(SQLSourceImplementation[MySQLSourceConfig, pymysql.Connection, Cursor]):
    """MySQL driver implementation paired with `MySQLSource`.

    One class owns everything MySQL-specific: the SSH tunnel + pymysql
    connection lifecycle, `information_schema`-style batch queries used
    during schema listing, per-cursor metadata used during the streaming
    sync (primary keys, column types, row counts, partition/chunk sizing,
    `FORCE INDEX` index lookup, `EXPLAIN` diagnostics), and the dlt
    pipeline factory (`build_pipeline`).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(
        self,
        config: MySQLSourceConfig,
        *,
        read_timeout: int | None = None,
    ) -> Iterator[pymysql.Connection]:
        """Open a pymysql connection for the duration of the context.

        Opens the SSH tunnel (if configured), then connects with the
        MySQL-wide conventions: safe date/datetime converters, and a
        PlanetScale workload hint injected automatically when the host
        resolves to a `*.psdb.cloud` address. Callers only vary one
        thing — the streaming path sets `read_timeout=STATEMENT_TIMEOUT_SECONDS`
        so multi-GB filesorts don't drop on middlebox timeouts before the
        first rows are ready.
        """
        ssl_ca: str | None = None
        if config.using_ssl:
            ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        with open_ssh_tunnel(config) as (host, port):
            kwargs: dict[str, Any] = {
                "host": host,
                "port": port,
                "database": config.database,
                "user": config.user,
                "password": config.password,
                "connect_timeout": 10,
                "ssl_ca": ssl_ca,
                "conv": _MYSQL_SAFE_CONVERSIONS,
                "init_command": "SET workload = 'OLAP';" if host.endswith("psdb.cloud") else None,
            }
            if read_timeout is not None:
                kwargs["read_timeout"] = read_timeout
            with pymysql.connect(**kwargs) as conn:
                yield conn

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        params: dict[str, Any] = {"schema": config.schema}
        names_filter = ""
        if names:
            params["names"] = tuple(names)
            names_filter = "AND table_name IN %(names)s"

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name, data_type, is_nullable"
                " FROM information_schema.columns"
                f" WHERE table_schema = %(schema)s {names_filter}"
                " ORDER BY table_name ASC",
                params,
            )
            rows = cursor.fetchall()

        result: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for table_name, column_name, data_type, is_nullable in rows:
            result[table_name].append((column_name, data_type, is_nullable == "YES"))
        return dict(result)

    def get_primary_keys(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for every table in a single query.

        Permission-sensitive — some MySQL deployments restrict access to
        `information_schema.TABLE_CONSTRAINTS`. Swallow and log any
        failure so schema discovery keeps working without PKs.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tc.TABLE_NAME, kcu.COLUMN_NAME
                    FROM information_schema.TABLE_CONSTRAINTS tc
                    JOIN information_schema.KEY_COLUMN_USAGE kcu
                    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    AND tc.TABLE_NAME = kcu.TABLE_NAME
                    WHERE tc.TABLE_SCHEMA = %(schema)s
                    AND tc.TABLE_NAME IN %(names)s
                    AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    """,
                    {"schema": config.schema, "names": tuple(tables)},
                )
                rows = cursor.fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for MySQL schemas", exc_info=e)
            return result

        pks: dict[str, list[str]] = collections.defaultdict(list)
        for table_name, column_name in rows:
            pks[table_name].append(column_name)
        for table_name, pk_cols in pks.items():
            result[table_name] = pk_cols
        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_mysql_incremental_fields

    def get_leading_index_columns(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the leading column of each index per table.

        `information_schema.STATISTICS` lists every index (primary, unique,
        secondary) one row per column. `SEQ_IN_INDEX = 1` identifies the
        first column of each index, which is what speeds up
        `WHERE col >= …` predicates. Returns `None` when discovery fails
        so the caller defaults to no warning; tables with no indexes still
        appear with an empty set so the UI can distinguish them from
        "lookup failed".
        """
        if not tables:
            return {}

        result: dict[str, set[str]] = {table: set() for table in tables}
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT TABLE_NAME, COLUMN_NAME
                    FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = %(schema)s
                      AND TABLE_NAME IN %(names)s
                      AND SEQ_IN_INDEX = 1
                    """,
                    {"schema": config.schema, "names": tuple(tables)},
                )
                for table_name, column_name in cursor.fetchall():
                    result.setdefault(table_name, set()).add(column_name)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect leading index columns for MySQL schemas", exc_info=e)
            return None
        return result

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(self, cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
        """Return the primary-key column names for a single table, or None."""
        cursor.execute(
            """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %(schema)s
                AND TABLE_NAME = %(table_name)s
                AND COLUMN_KEY = 'PRI'
            """,
            {"schema": schema, "table_name": table_name},
        )
        rows = cursor.fetchall()
        if len(rows) > 0:
            return [row[0] for row in rows]
        return None

    def get_table_metadata(self, cursor: Cursor, schema: str, table_name: str) -> Table[MySQLColumn]:
        """Return rich column metadata for building a PyArrow schema."""
        cursor.execute(
            """
                SELECT
                    column_name,
                    data_type,
                    column_type,
                    is_nullable,
                    numeric_precision,
                    numeric_scale
                FROM
                    information_schema.columns
                WHERE
                    table_schema = %(schema)s
                    AND table_name = %(table_name)s
            """,
            {"schema": schema, "table_name": table_name},
        )

        numeric_data_types = {"numeric", "decimal"}
        columns = []
        for name, data_type, column_type, nullable, numeric_precision_candidate, numeric_scale_candidate in cursor:
            if data_type in numeric_data_types:
                numeric_precision = (
                    numeric_precision_candidate
                    if numeric_precision_candidate is not None
                    else DEFAULT_NUMERIC_PRECISION
                )
                numeric_scale = (
                    numeric_scale_candidate if numeric_scale_candidate is not None else DEFAULT_NUMERIC_SCALE
                )
            else:
                numeric_precision = None
                numeric_scale = None

            columns.append(
                MySQLColumn(
                    name=name,
                    data_type=data_type,
                    column_type=column_type,
                    nullable=nullable,
                    numeric_precision=numeric_precision,
                    numeric_scale=numeric_scale,
                )
            )

        return Table(name=table_name, parents=(schema,), columns=columns)

    def get_rows_to_sync(
        self,
        cursor: Cursor,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce. Returns 0 on error."""
        try:
            # The MAX_EXECUTION_TIME optimizer hint bounds this probe at 60s —
            # we'd rather return 0 and let the sync proceed than block here.
            query = f"SELECT /*+ MAX_EXECUTION_TIME(60000) */ COUNT(*) FROM ({inner_query}) as t"

            cursor.execute(query, inner_query_args)
            row = cursor.fetchone()

            if row is None:
                logger.debug("get_rows_to_sync: No results returned. Using 0 as rows to sync")
                return 0

            rows_to_sync = row[0] or 0
            rows_to_sync_int = int(rows_to_sync)

            logger.debug(f"get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            capture_exception(e)
            return 0

    def fetch_table_stats(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return DATA_LENGTH / TABLE_ROWS for `schema.table_name`.

        `DATA_LENGTH` only covers values in the clustered index — types
        like `TEXT` are stored off-page, so the figure can under-count.
        `TABLE_ROWS` is an InnoDB estimate. Both are close enough to
        size partitions, and cheap compared to a `COUNT(*)` full scan
        that can time out on large tables.
        """
        query = """
            SELECT
                t.DATA_LENGTH AS table_size,
                t.TABLE_ROWS AS row_count
            FROM
                information_schema.TABLES AS t
            WHERE
                t.TABLE_SCHEMA = %(schema)s
                AND t.TABLE_NAME = %(table_name)s
        """
        logger.debug(f"fetch_table_stats: running query {query}")
        cursor.execute(query, {"schema": schema, "table_name": table_name})
        result = cursor.fetchone()
        if result is None:
            logger.debug("fetch_table_stats: no results returning None")
            return None

        table_size, row_count = result
        if table_size is None or row_count is None:
            logger.debug("fetch_table_stats: missing table_size or row_count, returning None")
            return None

        return TableStats(table_size_bytes=int(table_size), row_count=int(row_count))

    def fetch_average_row_size(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Sample `LENGTH(COALESCE(col, ''))` across columns on the first 1000 rows.

        The sampling SQL is built directly from `schema` / `table_name`
        rather than wrapping the sync's `inner_query`. On incremental
        syncs `inner_query` ends in `ORDER BY <cursor> ASC`, and
        MySQL / Vitess apply the inner `ORDER BY` before the outer
        `LIMIT` — sorting every qualifying row, blowing past
        `sort_buffer_size`, and raising errno 1038 ("Out of sort
        memory"). Chunk-size tuning only needs a rough per-row byte
        estimate, so dropping the incremental filter / ordering is
        acceptable here. `inner_query` / `inner_query_args` are kept
        for base-class signature compatibility but are intentionally
        unused.

        Column names are pulled from `information_schema.COLUMNS`, then
        each name is passed through the identifier quoter before being
        interpolated into the `LENGTH(...)` sum. The qualified table
        reference is quoted by the shared `SelectQueryBuilder`. No
        untrusted value ever reaches raw SQL.
        """
        del inner_query, inner_query_args  # see docstring
        try:
            cursor.execute(
                """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %(schema)s
                    AND TABLE_NAME = %(table_name)s
                    ORDER BY ORDINAL_POSITION
                """,
                {"schema": schema, "table_name": table_name},
            )
            rows = cursor.fetchall()
            if not rows:
                logger.debug("fetch_average_row_size: No columns found.")
                return None

            columns = [row[0] for row in rows]
            length_sum = " + ".join(f"LENGTH(COALESCE({_IDENTIFIER_QUOTER.quote(col)}, ''))" for col in columns)
            sample_sql = _QUERY_BUILDER.select_all(schema=schema, table_name=table_name).sql
            # length_sum and sample_sql are built from sanitized identifiers;
            # no user-supplied values are interpolated into the SQL itself.
            size_query = "SELECT AVG(" + length_sum + ") as avg_row_size FROM (" + sample_sql + " LIMIT 1000) as t"

            cursor.execute(size_query)
            row = cursor.fetchone()

            if row is None or row[0] is None:
                logger.debug("fetch_average_row_size: No results returned.")
                return None

            row_size_bytes = max(row[0] or 0, 1)
            return int(row_size_bytes)
        except Exception as e:
            logger.debug(f"fetch_average_row_size: Error: {e}.", exc_info=e)
            capture_exception(e)
            return None

    def find_index_for_cursor(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        cursor_field: str,
        logger: FilteringBoundLogger,
    ) -> str | None:
        """Return an index whose leading column equals `cursor_field`.

        Used for the `FORCE INDEX (...)` retry when the optimizer picks
        a full table scan over the incremental field's index.
        Identifiers are quoted before being interpolated into
        `SHOW INDEX FROM ...`; `SHOW INDEX` has no parameterized form in
        MySQL.
        """
        try:
            query = f"SHOW INDEX FROM {_IDENTIFIER_QUOTER.quote(schema)}.{_IDENTIFIER_QUOTER.quote(table_name)}"
            cursor.execute(query)
            rows = cursor.fetchall()
            column_names = [col[0] for col in cursor.description or []]
            # SHOW INDEX column positions vary by MySQL version; look them up by name.
            try:
                key_name_idx = column_names.index("Key_name")
                seq_idx = column_names.index("Seq_in_index")
                column_idx = column_names.index("Column_name")
            except ValueError:
                logger.debug("SHOW INDEX returned unexpected columns: %s", column_names)
                return None

            for row in rows:
                if row[column_idx] == cursor_field and row[seq_idx] == 1:
                    return row[key_name_idx]
            return None
        except Exception as e:
            logger.debug(f"find_index_for_cursor failed: {e}", exc_info=e)
            return None

    def explain_query(
        self,
        cursor: Cursor,
        query: str,
        query_args: Any,
        logger: FilteringBoundLogger,
    ) -> None:
        """Log MySQL `EXPLAIN` output for `query` at debug level.

        Used to diagnose sync failures on large tables — reveals whether
        the optimizer chose full-scan + filesort vs. a range scan on the
        incremental index.
        """
        try:
            explain_query = f"EXPLAIN {query}"
            logger.debug(f"Running EXPLAIN on: {query}")
            cursor.execute(explain_query, query_args)
            rows = cursor.fetchall()
            column_names = [col[0] for col in cursor.description or []]
            explain_lines = [str(dict(zip(column_names, row))) for row in rows]
            logger.debug(f"EXPLAIN result: {' | '.join(explain_lines) if explain_lines else '(empty)'}")
        except Exception as e:
            logger.debug(f"EXPLAIN raised an exception: {e}", exc_info=e)
            capture_exception(e)

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: MySQLSourceConfig, inputs: SourceInputs) -> SourceResponse:
        table_name = inputs.schema_name
        if not table_name:
            raise ValueError("Table name is missing")

        schema = config.schema
        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value

        with self.connect(config) as connection:
            with connection.cursor() as cursor:
                inner_query, inner_query_args = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )

                primary_keys = self.get_primary_keys_for_table(cursor, schema, table_name)
                table = self.get_table_metadata(cursor, schema, table_name)
                arrow_schema = table.to_arrow_schema()
                logger.debug(f"Source schema: {arrow_schema}")
                rows_to_sync = self.get_rows_to_sync(cursor, inner_query, inner_query_args, logger)
                chunk_size = self.get_chunk_size(cursor, schema, table_name, inner_query, inner_query_args, logger)
                partition_settings = (
                    self.get_partition_settings(cursor, schema, table_name, logger)
                    if should_use_incremental_field
                    else None
                )

                # Fallback on checking for an `id` field on the table
                if primary_keys is None and "id" in table:
                    primary_keys = ["id"]

        def _stream_with_optional_force_index(force_index_name: str | None) -> Iterator[Any]:
            """Open a fresh connection and stream rows.

            The pipeline itself persists the per-batch cursor value (see
            `update_incremental_field_values`), so a retry that restarts
            from the original starting cursor is correct but occasionally
            replays a few already-processed rows; the delta merge
            dedupes by primary key.
            """
            with self.connect(config, read_timeout=STATEMENT_TIMEOUT_SECONDS) as streaming_connection:
                # Bump server-side timeouts for large table scans. The
                # defaults (60s each) are too low for multi-GB unbuffered
                # queries — the server drops the connection before the
                # first rows are ready.
                try:
                    with streaming_connection.cursor() as setup_cursor:
                        setup_cursor.execute(
                            f"SET SESSION net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}, net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to set session timeouts on MySQL sync connection: {e}")
                with streaming_connection.cursor(SSCursor) as ss_cursor:
                    query, args = _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        force_index_name=force_index_name,
                    )
                    logger.debug(f"MySQL query: {query.format(args)}")

                    # EXPLAIN before the streaming query to help
                    # diagnose failures where MySQL picks full scan
                    # + filesort over the incremental index.
                    # `explain_query` consumes its rows via
                    # fetchall(), leaving the cursor in a clean
                    # state for the streaming execute() below.
                    self.explain_query(ss_cursor, query, args, logger)

                    ss_cursor.execute(query, args)

                    column_names = [column[0] for column in ss_cursor.description or []]

                    while True:
                        # use chunk_size to fetch rows instead of DEFAULT_CHUNK_SIZE
                        batch = ss_cursor.fetchmany(chunk_size)
                        if not batch:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in batch), arrow_schema)

        def get_rows() -> Iterator[Any]:
            # Track whether any batch reached the pipeline. If one did,
            # the retry path can't safely restart from the original
            # cursor: the delta merge only dedupes rows for `incremental`
            # writes into an existing table (see
            # `delta_table_helper.write_to_deltalake`), so full-refresh
            # and first-ever-sync scenarios would get silent duplicates
            # on replay. The observed bad-plan failure fails before any
            # rows stream, so this guard is defensive — it enforces the
            # invariant the PR assumes.
            yielded_any = False
            try:
                for chunk in _stream_with_optional_force_index(force_index_name=None):
                    yielded_any = True
                    yield chunk
                return
            except pymysql.err.OperationalError as e:
                if not _is_bad_plan_timeout(e):
                    raise
                if yielded_any:
                    logger.warning(
                        f"Streaming query died with bad-plan timeout (error {e.args[0] if e.args else '?'}) "
                        f"after already yielding rows — skipping FORCE INDEX fallback to avoid duplicates."
                    )
                    raise
                logger.warning(
                    f"Streaming query died with bad-plan timeout (error {e.args[0] if e.args else '?'}). "
                    f"Attempting FORCE INDEX fallback."
                )
                if not should_use_incremental_field or not incremental_field:
                    # Without an incremental field there's no cursor to force an index on.
                    logger.warning(
                        "Bad-plan timeout hit, but sync has no incremental field — cannot apply FORCE INDEX fallback."
                    )
                    raise

                with self.connect(config) as probe_connection:
                    with probe_connection.cursor() as probe_cursor:
                        force_index_name = self.find_index_for_cursor(
                            probe_cursor, schema, table_name, incremental_field, logger
                        )

                if not force_index_name:
                    logger.warning(
                        f"Bad-plan timeout hit and no usable index on "
                        f"{schema}.{table_name}.{incremental_field} — cannot apply FORCE INDEX fallback. "
                        f"Customer should add an index on the incremental field."
                    )
                    raise

                logger.warning(f"Retrying streaming query with FORCE INDEX ({force_index_name}) after bad-plan timeout")
                yield from _stream_with_optional_force_index(force_index_name)

        name = NamingConvention.normalize_identifier(table_name)

        return SourceResponse(
            name=name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
        )
