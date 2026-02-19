from __future__ import annotations

import math
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any, Literal, LiteralString, Optional, cast

import psycopg
import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from psycopg import sql
from psycopg.adapt import Loader
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.sources.common.sql import Column, Table

from products.data_warehouse.backend.types import IncrementalFieldType, PartitionSettings


def filter_redshift_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    """Filter columns that can be used as incremental fields for Redshift."""
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type in ("integer", "smallint", "bigint", "int", "int2", "int4", "int8"):
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_redshift_row_count(
    host: str, port: int, database: str, user: str, password: str, schema: str
) -> dict[str, int]:
    """Get row counts for all tables in a Redshift schema."""
    connection = psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        sslmode="require",
        connect_timeout=15,
        sslrootcert="/tmp/no.txt",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
        options="-c client_encoding=UTF8",
    )

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(1000 * 30))  # 30 secs
            )

            cursor.execute(
                """
                SELECT "table" AS table_name, tbl_rows AS row_count
                FROM svv_table_info
                WHERE schema = %(schema)s
                """,
                {"schema": schema},
            )
            row_count_result = cursor.fetchall()
            row_counts = {row[0]: int(row[1]) for row in row_count_result}

            cursor.execute(
                "SELECT viewname FROM pg_views WHERE schemaname = %(schema)s",
                {"schema": schema},
            )
            views = cursor.fetchall()

            if views:
                view_counts = [
                    sql.SQL("SELECT {view_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{view}").format(
                        view_name=sql.Literal(view[0]),
                        schema=sql.Identifier(schema),
                        view=sql.Identifier(view[0]),
                    )
                    for view in views
                ]
                cursor.execute(sql.SQL(" UNION ALL ").join(view_counts))
                for row in cursor.fetchall():
                    row_counts[row[0]] = int(row[1])

        return row_counts
    except Exception:
        return {}
    finally:
        connection.close()


def get_schemas(
    host: str, database: str, user: str, password: str, schema: str, port: int
) -> dict[str, list[tuple[str, str]]]:
    """Get all tables from Redshift source schemas to sync."""
    connection = psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        sslmode="require",
        connect_timeout=15,
        sslrootcert="/tmp/no.txt",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
        options="-c client_encoding=UTF8",
    )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %(schema)s
            ORDER BY table_name ASC
            """,
            {"schema": schema},
        )
        result = cursor.fetchall()

        schema_list = collections.defaultdict(list)
        for row in result:
            schema_list[row[0]].append((row[1], row[2]))

    connection.close()

    return schema_list


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

    if add_sampling:
        # Redshift doesn't support TABLESAMPLE SYSTEM
        query = sql.SQL(
            "SELECT * FROM {schema}.{table} WHERE {incremental_field} > {last_value} AND random() < 0.01"
        ).format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            last_value=sql.Literal(db_incremental_field_last_value),
        )
    else:
        query = sql.SQL("SELECT * FROM {schema}.{table} WHERE {incremental_field} > {last_value}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
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


def _get_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> list[str] | None:
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
            AND tc.constraint_type = 'PRIMARY KEY'""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, query, logger)
    logger.debug(f"Running query: {query.as_string()}")
    cursor.execute(query)
    rows = cursor.fetchall()
    if len(rows) > 0:
        return [row[0] for row in rows]

    logger.warning(
        f"No primary keys found for {table_name}. If the table is not a view, (a) does the table have a primary key set? (b) is the primary key returned from querying information_schema?"
    )

    return None


def _has_duplicate_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, primary_keys: list[str] | None, logger: FilteringBoundLogger
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
            *[sql.Identifier(key) for key in primary_keys], sql.Identifier(schema), sql.Identifier(table_name)
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


def _get_table_chunk_size(cursor: psycopg.Cursor, inner_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    try:
        # Note: pg_column_size works in Redshift but may have slight differences
        query = sql.SQL("""
            SELECT percentile_cont(0.95) within group (order by subquery.row_size) FROM (
                SELECT pg_column_size(t) as row_size FROM ({}) as t
            ) as subquery
        """).format(inner_query)

        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_table_chunk_size: No results returned. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}")
            return DEFAULT_CHUNK_SIZE

        row_size_bytes = row[0] or 1
        chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)
        logger.debug(
            f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={chunk_size}"
        )

        return chunk_size
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


def _get_rows_to_sync(cursor: psycopg.Cursor, inner_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    try:
        query = sql.SQL("""
            SELECT COUNT(*) FROM ({}) as t
        """).format(inner_query)

        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug("_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field is set as a SORTKEY on the table"
            )

        return 0


def _get_partition_settings(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    # Redshift uses different function for table size - using SVV_TABLE_INFO
    query = sql.SQL("""
        SELECT
            CASE WHEN tbl_rows = 0 OR size = 0 THEN NULL
            ELSE round({bytes_per_partition} / ((size * 1024 * 1024) / tbl_rows)) END,
            tbl_rows
        FROM svv_table_info
        WHERE schema = {schema} AND "table" = {table}
    """).format(
        bytes_per_partition=sql.Literal(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES),
        schema=sql.Literal(schema),
        table=sql.Literal(table_name),
    )

    try:
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        capture_exception(e)
        logger.debug(f"_get_partition_settings: returning None due to error: {e}")
        return None

    result = cursor.fetchone()

    if result is None or len(result) == 0 or result[0] is None:
        logger.debug("_get_partition_settings: query result is None, returning None")
        return None

    partition_size = int(result[0])
    total_rows = int(result[1])
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        logger.debug(f"_get_partition_settings: partition_count=1, partition_size={partition_size}")
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    logger.debug(f"_get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


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


def _get_table(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> Table[RedshiftColumn]:
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


def redshift_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with tunnel() as (host, port):
        with psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode="require",
            connect_timeout=15,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
            options="-c client_encoding=UTF8",
        ) as connection:
            with connection.cursor() as cursor:
                logger.debug("Getting table types...")
                table = _get_table(cursor, schema, table_name, logger)

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
                    primary_keys = _get_primary_keys(cursor, schema, table_name, logger)
                    if primary_keys:
                        logger.debug(f"Found primary keys: {primary_keys}")
                    logger.debug("Getting table chunk size...")
                    if chunk_size_override is not None:
                        chunk_size = chunk_size_override
                        logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                    else:
                        chunk_size = _get_table_chunk_size(cursor, inner_query_with_limit, logger)
                    logger.debug("Getting rows to sync...")
                    rows_to_sync = _get_rows_to_sync(cursor, inner_query_without_limit, logger)
                    logger.debug("Getting partition settings...")
                    partition_settings = (
                        _get_partition_settings(cursor, schema, table_name, logger)
                        if should_use_incremental_field
                        else None
                    )
                    has_duplicate_primary_keys = False

                    # Fallback on checking for an `id` field on the table
                    if primary_keys is None and "id" in table:
                        logger.debug("Falling back to ['id'] for primary keys...")
                        primary_keys = ["id"]
                        logger.debug("Checking duplicate primary keys...")
                        has_duplicate_primary_keys = _has_duplicate_primary_keys(
                            cursor, schema, table_name, primary_keys, logger
                        )
                except psycopg.errors.QueryCanceled:
                    if should_use_incremental_field:
                        raise QueryTimeoutException(
                            f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) is set as a SORTKEY on the table"
                        )
                    raise

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()
        with tunnel() as (host, port):

            def get_connection():
                connection = psycopg.connect(
                    host=host,
                    port=port,
                    dbname=database,
                    user=user,
                    password=password,
                    sslmode="require",
                    connect_timeout=15,
                    sslrootcert="/tmp/no.txt",
                    sslcert="/tmp/no.txt",
                    sslkey="/tmp/no.txt",
                    options="-c client_encoding=UTF8",
                )
                connection.adapters.register_loader("json", JsonAsStringLoader)
                return connection

            with get_connection() as connection:
                with connection.cursor() as cursor:
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

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=lambda: get_rows(chunk_size),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
    )
