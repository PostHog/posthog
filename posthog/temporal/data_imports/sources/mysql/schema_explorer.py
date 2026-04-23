"""MySQL implementation of `SchemaExplorer`.

All driver-specific metadata queries for MySQL live here. Any code in
`mysql.py` that needs to introspect a MySQL schema at sync time goes
through `MySQLSchemaExplorer` — primary keys, column types, row counts,
table stats, row-size sampling, cursor-index lookup, `EXPLAIN`.

Queries use parameterized placeholders (`%(schema)s`, `%(table_name)s`)
everywhere. Identifiers that must be interpolated into raw SQL
(`FORCE INDEX (...)`, `SHOW INDEX FROM ...`, the column list in the
row-size `LENGTH(...)` probe) are always passed through
`BacktickIdentifierQuoter`, which rejects anything outside a strict
allowlist. There is no code path that splices an untrusted string into
a query.
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from pymysql.cursors import Cursor
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    build_pyarrow_decimal_type,
)
from posthog.temporal.data_imports.sources.common.sql import (
    BacktickIdentifierQuoter,
    Column,
    SchemaExplorer,
    Table,
    TableStats,
)


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
                if not self.numeric_precision or not self.numeric_scale:
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


class MySQLSchemaExplorer(SchemaExplorer[Cursor, MySQLColumn]):
    """MySQL implementation of `SchemaExplorer` — all INFORMATION_SCHEMA queries in one place."""

    def __init__(self, quoter: BacktickIdentifierQuoter | None = None) -> None:
        self._quoter = quoter or BacktickIdentifierQuoter()

    # ------------------------------------------------------------------
    # Primary keys
    # ------------------------------------------------------------------

    def get_primary_keys(self, cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
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

    # ------------------------------------------------------------------
    # Column metadata for the PyArrow schema
    # ------------------------------------------------------------------

    def get_table(self, cursor: Cursor, schema: str, table_name: str) -> Table[MySQLColumn]:
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
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
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

    # ------------------------------------------------------------------
    # Row counts / table stats
    # ------------------------------------------------------------------

    def get_rows_to_sync(
        self,
        cursor: Cursor,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
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

        `DATA_LENGTH` only covers values in the clustered index — types like
        `TEXT` are stored off-page, so the figure can under-count. `TABLE_ROWS`
        is an InnoDB estimate. Both are close enough to size partitions, and
        cheap compared to a `COUNT(*)` full scan that can time out on large
        tables.
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

    # ------------------------------------------------------------------
    # Row-size sampling for chunk sizing
    # ------------------------------------------------------------------

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

        Column names are pulled from `information_schema.COLUMNS`, then each
        name is passed through the identifier quoter before being interpolated
        into the `LENGTH(...)` sum. `inner_query` is the SELECT the sync is
        about to run — its identifiers were already quoted by the shared
        `SelectQueryBuilder`, and its arguments are rebound as parameters
        here. No untrusted value ever reaches raw SQL.
        """
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
            length_sum = " + ".join(f"LENGTH(COALESCE({self._quoter.quote(col)}, ''))" for col in columns)
            # length_sum and inner_query are built from sanitized identifiers;
            # no user-supplied values are interpolated into the SQL itself.
            size_query = "SELECT AVG(" + length_sum + ") as avg_row_size FROM (" + inner_query + " LIMIT 1000) as t"

            cursor.execute(size_query, inner_query_args)
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

    # ------------------------------------------------------------------
    # Index discovery for the FORCE INDEX fallback
    # ------------------------------------------------------------------

    def find_index_for_cursor(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        cursor_field: str,
        logger: FilteringBoundLogger,
    ) -> str | None:
        """Return an index whose leading column equals `cursor_field`.

        Used for the `FORCE INDEX (...)` retry when the optimizer picks a full
        table scan over the incremental field's index. Identifiers are quoted
        before being interpolated into `SHOW INDEX FROM ...`; `SHOW INDEX` has
        no parameterized form in MySQL.
        """
        try:
            query = f"SHOW INDEX FROM {self._quoter.quote(schema)}.{self._quoter.quote(table_name)}"
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

    # ------------------------------------------------------------------
    # Diagnostic — not part of the formal interface, but lives here since
    # every caller is an explorer-adjacent operation.
    # ------------------------------------------------------------------

    def explain_query(
        self,
        cursor: Cursor,
        query: str,
        query_args: Any,
        logger: FilteringBoundLogger,
    ) -> None:
        """Log MySQL `EXPLAIN` output for `query` at debug level.

        Used to diagnose sync failures on large tables — reveals whether the
        optimizer chose full-scan + filesort vs. a range scan on the incremental
        index.
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
