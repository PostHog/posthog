"""Redshift driver for PostHog's data-warehouse import pipeline.

Everything Redshift-specific — psycopg connection lifecycle (with SSH
tunnel), schema listing, sortkey discovery, per-cursor metadata for the
streaming sync, and the dlt pipeline build — lives on
`RedshiftImplementation`. The source-class `RedshiftSource` is a thin
PostHog-layer wrapper that just holds an instance and validates
credentials.
"""

from __future__ import annotations

import collections
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Literal, LiteralString, Optional, cast

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql
from psycopg.adapt import Loader
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.naming_convention import NamingConvention
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs, SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from posthog.temporal.data_imports.sources.common.sql import Column, Table
from posthog.temporal.data_imports.sources.common.sql.implementation import SQLSourceImplementation, TableStats
from posthog.temporal.data_imports.sources.common.sql.incremental import IncrementalFieldFilter
from posthog.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType

__all__ = [
    "JsonAsStringLoader",
    "RedshiftColumn",
    "RedshiftImplementation",
    "filter_redshift_incremental_fields",
]


# Shared psycopg.connect kwargs for Redshift. SSL is required; the SSL
# cert paths are intentionally pointed at non-existent files so psycopg
# uses the system default verification without picking up an unintended
# client cert.
_REDSHIFT_CONNECT_OPTS: dict[str, Any] = {
    "sslmode": "require",
    "connect_timeout": 15,
    "sslrootcert": "/tmp/no.txt",
    "sslcert": "/tmp/no.txt",
    "sslkey": "/tmp/no.txt",
    "options": "-c client_encoding=UTF8",
}


def filter_redshift_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Filter columns that can be used as incremental fields for Redshift."""
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type in ("integer", "smallint", "bigint", "int", "int2", "int4", "int8"):
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    table_type: Literal["table", "view", "materialized_view"] | None,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_sampling: Optional[bool] = False,
) -> sql.Composed:
    if not should_use_incremental_field:
        if add_sampling:
            # Redshift doesn't support TABLESAMPLE SYSTEM, use random() instead
            query = sql.SQL("SELECT * FROM {} WHERE random() < 0.01").format(sql.Identifier(schema, table_name))
        else:
            query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, table_name))

        if add_sampling:
            query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
            return sql.SQL(query_with_limit).format()

        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = sql.SQL(incremental_type_to_operator(incremental_field_type))

    if add_sampling:
        # Redshift doesn't support TABLESAMPLE SYSTEM
        query = sql.SQL(
            "SELECT * FROM {schema}.{table} WHERE {incremental_field} {op} {last_value} AND random() < 0.01"
        ).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            op=operator,
            last_value=sql.Literal(db_incremental_field_last_value),
        )
    else:
        query = sql.SQL("SELECT * FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            op=operator,
            last_value=sql.Literal(db_incremental_field_last_value),
        )

    if add_sampling:
        query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
        return sql.SQL(query_with_limit).format()
    else:
        query_str = cast(LiteralString, f"{query.as_string()} ORDER BY {{incremental_field}} ASC")
        return sql.SQL(query_str).format(incremental_field=sql.Identifier(incremental_field))


def _explain_query(cursor: psycopg.Cursor, query: sql.Composed, logger: FilteringBoundLogger):
    logger.debug(f"Running EXPLAIN on {query.as_string()}")

    try:
        query_with_explain = sql.SQL("EXPLAIN {}").format(query)
        cursor.execute(query_with_explain)
        rows = cursor.fetchall()
        explain_result: str = ""
        for row in rows:
            for col in row:
                explain_result += f"\n{col}"
        logger.debug(f"EXPLAIN result: {explain_result}")
    except Exception as e:
        capture_exception(e)
        logger.debug(f"EXPLAIN raised an exception: {e}")


class RedshiftColumn(Column):
    """Implementation of the `Column` protocol for a Redshift source."""

    def __init__(
        self,
        name: str,
        data_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        match self.data_type.lower():
            case "bigint" | "int8":
                arrow_type = pa.int64()
            case "integer" | "int" | "int4":
                arrow_type = pa.int32()
            case "smallint" | "int2":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")
                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "real" | "float4":
                arrow_type = pa.float32()
            case "double precision" | "float8" | "float":
                arrow_type = pa.float64()
            case "text" | "varchar" | "character varying" | "char" | "character" | "bpchar" | "nchar" | "nvarchar":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "time" | "time without time zone":
                arrow_type = pa.time64("us")
            case "timestamp" | "timestamp without time zone":
                arrow_type = pa.timestamp("us")
            case "timestamptz" | "timestamp with time zone":
                arrow_type = pa.timestamp("us", tz="UTC")
            case "boolean" | "bool":
                arrow_type = pa.bool_()
            case "super":
                # Redshift SUPER type for semi-structured data
                arrow_type = pa.string()
            case "geometry" | "geography":
                arrow_type = pa.string()
            case "hllsketch":
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


class RedshiftImplementation(SQLSourceImplementation[RedshiftSourceConfig, psycopg.Connection, Any]):  # noqa: type-var
    # `psycopg.Cursor` does not satisfy `_CursorLike` (its `execute`
    # signature uses `params` instead of `args`, and accepts `Query`
    # rather than `str`), so the cursor type is widened to `Any` here.
    """Redshift driver implementation paired with `RedshiftSource`.

    Owns the full Redshift lifecycle — SSH tunnel + psycopg connection,
    `information_schema` and `svv_table_info` batch listing queries used
    during schema discovery, per-cursor metadata used during the
    streaming sync, and the dlt pipeline factory (`build_pipeline`).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: RedshiftSourceConfig) -> Iterator[psycopg.Connection]:
        """Open a psycopg connection for the duration of the context.

        Opens the SSH tunnel (if configured) and connects with the
        Redshift-wide SSL conventions in one place — every listing
        method takes the resulting connection, so discovery against an
        SSH-tunneled cluster only opens the tunnel once.
        """
        with open_ssh_tunnel(config) as (host, port):
            with psycopg.connect(
                host=host,
                port=port,
                dbname=config.database,
                user=config.user,
                password=config.password,
                **_REDSHIFT_CONNECT_OPTS,
            ) as conn:
                yield conn

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        with conn.cursor() as cursor:
            params: dict = {"schema": config.schema}
            names_filter = ""
            if names:
                params["names"] = names
                names_filter = "AND table_name = ANY(%(names)s)"

            cursor.execute(
                f"""
                SELECT table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = %(schema)s {names_filter}
                ORDER BY table_name ASC
                """,
                params,
            )
            result = cursor.fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for row in result:
            schema_list[row[0]].append((row[1], row[2], row[3] == "YES"))
        return dict(schema_list)

    def get_primary_keys(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for all tables in a single query.

        Permission-sensitive — some Redshift deployments restrict access
        to `information_schema.table_constraints`. Swallow and log any
        failure so schema discovery keeps working without PKs.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("""
                        SELECT tc.table_name, kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                        AND tc.table_name = kcu.table_name
                        WHERE tc.table_schema = {schema}
                        AND tc.table_name = ANY({names})
                        AND tc.constraint_type = 'PRIMARY KEY'
                    """).format(schema=sql.Literal(config.schema), names=sql.Literal(tables))
                )
                rows = cursor.fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for Redshift schemas", exc_info=e)
            return result

        pks: dict[str, list[str]] = collections.defaultdict(list)
        for table_name, column_name in rows:
            pks[table_name].append(column_name)
        for table_name, pk_cols in pks.items():
            result[table_name] = pk_cols
        return result

    def get_row_counts(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, int | None]:
        """Return per-table row counts using `svv_table_info` for tables and `COUNT(*)` for views.

        `svv_table_info.tbl_rows` is a Redshift system table that gives
        cheap row count estimates for materialized tables; views aren't
        in it, so they fall through to a (slower) `UNION ALL` of
        `COUNT(*)` queries. Errors are swallowed — schema discovery
        keeps working without row counts.
        """
        if not tables:
            return {}

        result: dict[str, int | None] = {}
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(1000 * 30))  # 30 secs
                )

                params: dict = {"schema": config.schema, "names": tables}
                cursor.execute(
                    """
                    SELECT "table" AS table_name, tbl_rows AS row_count
                    FROM svv_table_info
                    WHERE schema = %(schema)s AND "table" = ANY(%(names)s)
                    """,
                    params,
                )
                for table_name, row_count in cursor.fetchall():
                    result[table_name] = int(row_count)

                cursor.execute(
                    "SELECT viewname FROM pg_views WHERE schemaname = %(schema)s AND viewname = ANY(%(names)s)",
                    params,
                )
                views = cursor.fetchall()

                if views:
                    view_counts = [
                        sql.SQL("SELECT {view_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{view}").format(
                            view_name=sql.Literal(view[0]),
                            schema=sql.Identifier(config.schema),
                            view=sql.Identifier(view[0]),
                        )
                        for view in views
                    ]
                    cursor.execute(sql.SQL(" UNION ALL ").join(view_counts))
                    for row in cursor.fetchall():
                        result[row[0]] = int(row[1])
        except Exception:
            return {}

        return result

    def get_leading_index_columns(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the columns that drive `WHERE col >= …` predicate pushdown per table.

        Redshift is columnar with no traditional B-tree indexes; SORTKEYs are the
        structure that accelerates predicate pushdown. The `sortkey` value reported
        by `pg_table_def` encodes both the kind of sortkey and the column's
        position:

        - **Compound sortkeys** use positive integers (1, 2, 3, …) where ``sortkey = 1``
          is the leading column. Only the leading column meaningfully accelerates
          `WHERE col >= …`; subsequent columns require equality predicates on
          preceding columns to be useful.
        - **Interleaved sortkeys** mix signs (e.g. ``-1, 2, -3, 4``). All non-zero
          sortkey columns contribute equally to predicate pushdown by design — the
          whole point of interleaved sortkeys is to give every column equal
          weight. Treating only ``sortkey = -1`` as indexed produces false warnings
          on the other interleaved columns.

        Returns None when discovery fails so the caller defaults to no-warning.
        Tables with no sortkey return an empty set so the warning fires.
        """
        if not tables:
            return {}

        result: dict[str, set[str]] = {table: set() for table in tables}

        try:
            with conn.cursor() as cursor:
                # pg_table_def only returns rows for schemas in search_path; without
                # this SET, schema=anything-other-than-public-or-the-username silently
                # returns zero rows and the helper marks every sortkey column as
                # unindexed. Documented behavior: docs.aws.amazon.com/redshift/latest/dg/r_PG_TABLE_DEF.html
                cursor.execute(sql.SQL("SET search_path TO {schema}").format(schema=sql.Identifier(config.schema)))
                cursor.execute(
                    sql.SQL("""
                        SELECT tablename, "column", sortkey
                        FROM pg_table_def
                        WHERE schemaname = {schema}
                          AND tablename = ANY({names})
                          AND sortkey != 0
                    """).format(schema=sql.Literal(config.schema), names=sql.Literal(tables))
                )
                # Group rows by table so we can classify compound vs interleaved
                # before deciding which columns count as indexed. Negative sortkey
                # values are the marker Redshift uses for interleaved sortkeys.
                rows_by_table: dict[str, list[tuple[str, int]]] = {}
                for table_name, column_name, sortkey_value in cursor.fetchall():
                    rows_by_table.setdefault(table_name, []).append((column_name, sortkey_value))

                for table_name, sortkey_rows in rows_by_table.items():
                    is_interleaved = any(sk < 0 for _, sk in sortkey_rows)
                    if is_interleaved:
                        result[table_name] = {col for col, _ in sortkey_rows}
                    else:
                        result[table_name] = {col for col, sk in sortkey_rows if sk == 1}
        except Exception as e:
            structlog.get_logger().warning("Failed to detect sortkeys for Redshift schemas", exc_info=e)
            return None

        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_redshift_incremental_fields

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger | None = None,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table, or None."""
        query = sql.SQL("""
            SELECT
                kcu.column_name
            FROM
                information_schema.table_constraints tc
            JOIN
                information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE
                tc.table_schema = {schema}
                AND tc.table_name = {table}
                AND tc.constraint_type = 'PRIMARY KEY'""").format(
            schema=sql.Literal(schema), table=sql.Literal(table_name)
        )

        if logger is not None:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        rows = cursor.fetchall()
        if len(rows) > 0:
            return [row[0] for row in rows]

        if logger is not None:
            logger.warning(
                f"No primary keys found for {table_name}. If the table is not a view, (a) does the table have a primary key set? (b) is the primary key returned from querying information_schema?"
            )
        return None

    def has_duplicate_primary_keys(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        primary_keys: list[str] | None,
        logger: FilteringBoundLogger,
    ) -> bool:
        if not primary_keys or len(primary_keys) == 0:
            return False

        try:
            sql_query = cast(
                LiteralString,
                f"""
                SELECT {", ".join(["{}" for _ in primary_keys])}
                FROM {{}}.{{}}
                GROUP BY {", ".join([str(i + 1) for i, _ in enumerate(primary_keys)])}
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
            )
            query = sql.SQL(sql_query).format(
                *[sql.Identifier(key) for key in primary_keys],
                sql.Identifier(schema),
                sql.Identifier(table_name),
            )
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
            cursor.execute(query)
            row = cursor.fetchone()
            return row is not None
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as e:
            capture_exception(e)
            return False

    def get_table_metadata(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger | None = None,
    ) -> Table[RedshiftColumn]:
        """Return rich column metadata for building a PyArrow schema."""
        # Check if it's a view
        is_view_query = sql.SQL(
            "SELECT {table} IN (SELECT viewname FROM pg_views WHERE schemaname = {schema}) as res"
        ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
        is_view_res = cursor.execute(is_view_query).fetchone()
        is_view = is_view_res is not None and is_view_res[0] is True

        query = sql.SQL("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                numeric_precision,
                numeric_scale
            FROM
                information_schema.columns
            WHERE
                table_schema = {schema}
                AND table_name = {table}""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

        if logger is not None:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)

        numeric_data_types = {"numeric", "decimal"}
        columns = []
        for name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate in cursor:
            if data_type in numeric_data_types:
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
            else:
                numeric_precision = None
                numeric_scale = None

            columns.append(
                RedshiftColumn(
                    name=name,
                    data_type=data_type,
                    nullable=nullable == "YES",
                    numeric_precision=numeric_precision,
                    numeric_scale=numeric_scale,
                )
            )

        table_type: Literal["view", "table"] = "view" if is_view else "table"
        return Table(name=table_name, parents=(schema,), columns=columns, type=table_type)

    def get_rows_to_sync(
        self,
        cursor: psycopg.Cursor,
        inner_query: Any,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce.

        Overrides the base helper to (1) let `psycopg.errors.QueryCanceled`
        bubble out so `build_pipeline` can promote it to
        `QueryTimeoutException`, and (2) promote Redshift's
        `temporary file size exceeds temp_file_limit` to
        `TemporaryFileSizeExceedsLimitException` — both are listed in
        `get_non_retryable_errors` and need to escape the base's catch-all
        `except Exception` that otherwise returns 0.
        """
        try:
            query = sql.SQL("SELECT COUNT(*) FROM ({}) as t").format(inner_query)
            cursor.execute(query)
            row = cursor.fetchone()
            if row is None:
                return 0
            return int(row[0] or 0)
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            capture_exception(e)
            if "temporary file size exceeds temp_file_limit" in str(e):
                raise TemporaryFileSizeExceedsLimitException(
                    f"Error: {e}. Please ensure your incremental field is set as a SORTKEY on the table"
                )
            return 0

    def fetch_table_stats(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return `size` (in MB) and `tbl_rows` from `svv_table_info`.

        `size` is reported in megabytes by Redshift's system table —
        converted to bytes here so the shared `get_partition_settings`
        math operates on a single unit. Returns None when either value
        is missing or zero so the base falls back to no partitioning.
        """
        query = sql.SQL("""
            SELECT size, tbl_rows
            FROM svv_table_info
            WHERE schema = {schema} AND "table" = {table}
        """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))

        try:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
            cursor.execute(query)
            result = cursor.fetchone()
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as e:
            capture_exception(e)
            logger.debug(f"fetch_table_stats: returning None due to error: {e}")
            return None

        if result is None:
            logger.debug("fetch_table_stats: no results returning None")
            return None

        size_mb, tbl_rows = result
        if size_mb is None or tbl_rows is None or size_mb == 0 or tbl_rows == 0:
            logger.debug("fetch_table_stats: missing or zero size/rows, returning None")
            return None

        return TableStats(table_size_bytes=int(size_mb) * 1024 * 1024, row_count=int(tbl_rows))

    def fetch_average_row_size(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        inner_query: Any,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Sample the 95th percentile of `pg_column_size(t)` across the filtered query.

        `inner_query` is a `psycopg.sql.Composed` whose literals are
        already bound — no separate `inner_query_args` is interpolated
        here, mirroring how the rest of the Redshift driver builds
        queries.
        """
        try:
            query = sql.SQL("""
                SELECT percentile_cont(0.95) within group (order by subquery.row_size) FROM (
                    SELECT pg_column_size(t) as row_size FROM ({}) as t
                ) as subquery
            """).format(inner_query)

            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
            cursor.execute(query)
            row = cursor.fetchone()

            if row is None or row[0] is None:
                logger.debug("fetch_average_row_size: no results returning None")
                return None

            return int(row[0] or 1)
        except psycopg.errors.QueryCanceled:
            raise
        except Exception as e:
            logger.debug(f"fetch_average_row_size: Error: {e}", exc_info=e)
            capture_exception(e)
            return None

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(
        self,
        config: RedshiftSourceConfig,
        inputs: SourceInputs,
        *,
        chunk_size_override: int | None = None,
    ) -> SourceResponse:
        # `chunk_size_override` is sourced from
        # `ExternalDataSchema.sync_type_config` by the caller
        # (`RedshiftSource.source_for_pipeline`) — keeping the ORM
        # lookup at the source layer lets the driver stay free of
        # Django model imports.
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
                logger.debug("Getting table types...")
                table = self.get_table_metadata(cursor, schema, table_name, logger)
                logger.debug(f"Source schema: {table.to_arrow_schema()}")

                inner_query_with_limit = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    table.type,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    add_sampling=True,
                )

                inner_query_without_limit = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    table.type,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                cursor.execute(
                    sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(1000 * 60 * 10))  # 10 mins
                )
                try:
                    logger.debug("Getting primary keys...")
                    primary_keys = self.get_primary_keys_for_table(cursor, schema, table_name, logger)
                    if primary_keys:
                        logger.debug(f"Found primary keys: {primary_keys}")
                    logger.debug("Getting table chunk size...")
                    if chunk_size_override is not None:
                        chunk_size = chunk_size_override
                        logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                    else:
                        # `inner_query_with_limit` is a `psycopg.sql.Composed`
                        # rather than a `str`; the override on
                        # `fetch_average_row_size` accepts it via `Any`.
                        chunk_size = self.get_chunk_size(
                            cursor,
                            schema,
                            table_name,
                            inner_query_with_limit,  # type: ignore[arg-type]
                            None,
                            logger,
                        )
                    logger.debug("Getting rows to sync...")
                    rows_to_sync = self.get_rows_to_sync(cursor, inner_query_without_limit, None, logger)
                    logger.debug("Getting partition settings...")
                    partition_settings = (
                        self.get_partition_settings(cursor, schema, table_name, logger)
                        if should_use_incremental_field
                        else None
                    )
                    duplicate_primary_keys = False

                    # Fallback on checking for an `id` field on the table
                    if primary_keys is None and "id" in table:
                        logger.debug("Falling back to ['id'] for primary keys...")
                        primary_keys = ["id"]
                        logger.debug("Checking duplicate primary keys...")
                        duplicate_primary_keys = self.has_duplicate_primary_keys(
                            cursor, schema, table_name, primary_keys, logger
                        )
                except psycopg.errors.QueryCanceled:
                    if should_use_incremental_field:
                        raise QueryTimeoutException(
                            f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) is set as a SORTKEY on the table"
                        )
                    raise

        def get_rows() -> Iterator[Any]:
            arrow_schema = table.to_arrow_schema()
            with self.connect(config) as streaming_connection:
                streaming_connection.adapters.register_loader("json", JsonAsStringLoader)
                with streaming_connection.cursor() as cursor:
                    query = _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        table.type,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                    )
                    logger.debug(f"Redshift query: {query.as_string()}")

                    cursor.execute(query)

                    column_names = [column.name for column in cursor.description or []]

                    while True:
                        rows = cursor.fetchmany(chunk_size)
                        if not rows:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

        name = NamingConvention.normalize_identifier(table_name)

        return SourceResponse(
            name=name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
            has_duplicate_primary_keys=duplicate_primary_keys,
        )
