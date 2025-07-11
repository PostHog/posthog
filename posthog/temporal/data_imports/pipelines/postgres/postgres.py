from __future__ import annotations

import collections
import math
from collections.abc import Iterator
from typing import Any, LiteralString, Optional, cast

import psycopg
import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from psycopg import sql
from psycopg.adapt import Loader

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
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
from posthog.temporal.data_imports.pipelines.source import config
from posthog.temporal.data_imports.pipelines.source.sql import Column, Table
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.warehouse.models.ssh_tunnel import SSHTunnel, SSHTunnelConfig
from posthog.warehouse.types import IncrementalFieldType, PartitionSettings


@config.config
class PostgreSQLSourceConfig(config.Config):
    host: str
    user: str
    password: str
    database: str
    schema: str
    port: int = config.value(converter=int)
    ssh_tunnel: SSHTunnelConfig | None = None


def get_schemas(config: PostgreSQLSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all tables from PostgreSQL source schemas to sync."""

    def inner(postgres_host: str, postgres_port: int):
        connection = psycopg.connect(
            host=postgres_host,
            port=postgres_port,
            dbname=config.database,
            user=config.user,
            password=config.password,
            sslmode="prefer",
            connect_timeout=5,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM (
                    SELECT table_name, column_name, data_type FROM information_schema.columns
                    WHERE table_schema = %(schema)s
                    UNION ALL
                    SELECT
                        c.relname AS table_name,
                        a.attname AS column_name,
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
                    FROM pg_class c
                    JOIN pg_namespace n ON c.relnamespace = n.oid
                    JOIN pg_attribute a ON a.attrelid = c.oid
                    WHERE c.relkind = 'm'  -- materialized view
                    AND n.nspname = %(schema)s
                    AND a.attnum > 0
                    AND NOT a.attisdropped
                ) t
                ORDER BY table_name ASC""",
                {"schema": config.schema},
            )
            result = cursor.fetchall()

            schema_list = collections.defaultdict(list)
            for row in result:
                schema_list[row[0]].append((row[1], row[2]))

        connection.close()

        return schema_list

    if config.ssh_tunnel and config.ssh_tunnel.enabled:
        ssh_tunnel = SSHTunnel.from_config(config.ssh_tunnel)

        with ssh_tunnel.get_tunnel(config.host, config.port) as tunnel:
            if tunnel is None:
                raise ConnectionError("Can't open tunnel to SSH server")

            return inner(tunnel.local_bind_host, tunnel.local_bind_port)

    return inner(config.host, config.port)


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class RangeAsStringLoader(Loader):
    """Load PostgreSQL range types as their string representation.

    We currently do not support range types. So, for now, the best we can do is
    convert them to `str`. For example, instead of loading a
    `psycopg.types.range.Range(4, 5, '[)')`, we will load `str` "[4,5)".

    Keep in mind that a single range can have multiple possible string
    representations. For example, `psycopg.types.range.Range(4, 5, '[]')` could
    be represented as "[4,5]" or "[4,6)". We let `psycopg` figure which string
    representation to use (from testing, it seems that the latter is preferred).
    """

    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_limit: Optional[bool] = False,
) -> sql.Composed:
    query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, table_name))

    if not should_use_incremental_field:
        if add_limit:
            query_with_limit = cast(LiteralString, f"{query.as_string()} ORDER BY RANDOM() LIMIT 100")
            return sql.SQL(query_with_limit).format()

        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = sql.SQL("SELECT * FROM {schema}.{table} WHERE {incremental_field} >= {last_value}").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        last_value=sql.Literal(db_incremental_field_last_value),
    )

    if add_limit:
        query_with_limit = cast(LiteralString, f"{query.as_string()} ORDER BY RANDOM() LIMIT 100")
        return sql.SQL(query_with_limit).format()
    else:
        query_str = cast(LiteralString, f"{query.as_string()} ORDER BY {{incremental_field}} ASC")
        return sql.SQL(query_str).format(incremental_field=sql.Identifier(incremental_field))


def _get_primary_keys(cursor: psycopg.Cursor, schema: str, table_name: str) -> list[str] | None:
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

    cursor.execute(query)
    rows = cursor.fetchall()
    if len(rows) > 0:
        return [row[0] for row in rows]

    return None


def _has_duplicate_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, primary_keys: list[str] | None
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
        query = sql.SQL("""
            SELECT SUM(pg_column_size(t.*)) / COUNT(t.*) FROM ({}) as t
        """).format(inner_query)

        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_table_chunk_size: No results returned. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}")
            return DEFAULT_CHUNK_SIZE

        row_size_bytes = row[0] or 1

        chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)

        min_chunk_size = min(chunk_size, DEFAULT_CHUNK_SIZE)

        logger.debug(
            f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={min_chunk_size}"
        )

        return min_chunk_size
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


def _get_rows_to_sync(cursor: psycopg.Cursor, inner_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    try:
        query = sql.SQL("""
            SELECT COUNT(t.*) FROM ({}) as t
        """).format(inner_query)

        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
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
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return 0


def _get_partition_settings(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    query = sql.SQL("""
        SELECT
            CASE WHEN count(*) = 0 OR pg_table_size({schema_table_name_literal}) = 0 THEN NULL
            ELSE round({bytes_per_partition} / (pg_table_size({schema_table_name_literal}) / count(*))) END,
            COUNT(*)
        FROM {schema}.{table}""").format(
        bytes_per_partition=sql.Literal(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES),
        schema_table_name_literal=sql.Literal(f'{schema}."{table_name}"'),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
    )

    try:
        cursor.execute(query)
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        capture_exception(e)
        logger.debug(f"_get_partition_settings: returning None due to error: {e}")
        return None

    result = cursor.fetchone()

    if result is None or len(result) == 0 or result[0] is None:
        logger.debug(f"_get_partition_settings: query result is None, returning None")
        return None

    partition_size = int(result[0])
    total_rows = int(result[1])
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        logger.debug(f"_get_partition_settings: partition_count=1, partition_size={partition_size}")
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    logger.debug(f"_get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


class PostgreSQLColumn(Column):
    """Implementation of the `Column` protocol for a PostgreSQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://www.postgresql.org/docs/current/datatype.html.
        nullable: Whether the column is nullable or not.
        numeric_precision: The number of significant digits. Only used with
            numeric `data_type`s, otherwise `None`.
        numeric_scale: The number of significant digits to the right of
            decimal point. Only used with numeric `data_type`s, otherwise
            `None`.
    """

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
            case "bigint":
                arrow_type = pa.int64()
            case "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "real":
                arrow_type = pa.float32()
            case "double precision":
                arrow_type = pa.float64()
            case "text" | "varchar" | "character varying":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "time" | "time without time zone":
                arrow_type = pa.time64("us")
            case "timestamp" | "timestamp without time zone":
                arrow_type = pa.timestamp("us")
            case "timestamptz" | "timestamp with time zone":
                arrow_type = pa.timestamp("us", tz="UTC")
            case "interval":
                arrow_type = pa.duration("us")
            case "boolean":
                arrow_type = pa.bool_()
            case "bytea":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json" | "jsonb":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _get_table(cursor: psycopg.Cursor, schema: str, table_name: str) -> Table[PostgreSQLColumn]:
    is_mat_view_query = sql.SQL(
        "select {table} in (select matviewname from pg_matviews where schemaname = {schema}) as res"
    ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    is_mat_view_res = cursor.execute(is_mat_view_query).fetchone()

    if is_mat_view_res is not None and is_mat_view_res[0] is True:
        # Table is a materialised view, column info doesn't exist in information_schema.columns
        query = sql.SQL("""
            SELECT
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull AS is_nullable,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE ((a.atttypmod - 4) >> 16) & 65535
                        END
                    ELSE NULL
                END AS numeric_precision,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE (a.atttypmod - 4) & 65535
                        END
                    ELSE NULL
                END AS numeric_scale
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_type t ON a.atttypid = t.oid
            WHERE c.relname = {table}
            AND n.nspname = {schema}
            AND a.attnum > 0
            AND NOT a.attisdropped""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    else:
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
            PostgreSQLColumn(
                name=name,
                data_type=data_type,
                nullable=nullable,
                numeric_precision=numeric_precision,
                numeric_scale=numeric_scale,
            )
        )

    return Table(
        name=table_name,
        parents=(schema,),
        columns=columns,
    )


def postgres_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with psycopg.connect(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        sslmode=sslmode,
        connect_timeout=5,
        sslrootcert="/tmp/no.txt",
        sslcert="/tmp/no.txt",
        sslkey="/tmp/no.txt",
    ) as connection:
        with connection.cursor() as cursor:
            inner_query_with_limit = _build_query(
                schema,
                table_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
                add_limit=True,
            )

            inner_query_without_limit = _build_query(
                schema,
                table_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                    timeout=sql.Literal(1000 * 60 * 10)  # 10 mins
                )
            )
            try:
                primary_keys = _get_primary_keys(cursor, schema, table_name)
                table = _get_table(cursor, schema, table_name)
                chunk_size = _get_table_chunk_size(cursor, inner_query_with_limit, logger)
                rows_to_sync = _get_rows_to_sync(cursor, inner_query_without_limit, logger)
                partition_settings = (
                    _get_partition_settings(cursor, schema, table_name, logger)
                    if should_use_incremental_field
                    else None
                )
                has_duplicate_primary_keys = False

                # Fallback on checking for an `id` field on the table
                if primary_keys is None and "id" in table:
                    primary_keys = ["id"]
                    has_duplicate_primary_keys = _has_duplicate_primary_keys(cursor, schema, table_name, primary_keys)
            except psycopg.errors.QueryCanceled:
                if should_use_incremental_field:
                    raise QueryTimeoutException(
                        f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) has an appropriate index created"
                    )
                raise
            except Exception:
                raise

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()

        with psycopg.connect(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode=sslmode,
            connect_timeout=5,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
            cursor_factory=psycopg.ServerCursor,
        ) as connection:
            connection.adapters.register_loader("json", JsonAsStringLoader)
            connection.adapters.register_loader("jsonb", JsonAsStringLoader)
            connection.adapters.register_loader("int4range", RangeAsStringLoader)
            connection.adapters.register_loader("int8range", RangeAsStringLoader)
            connection.adapters.register_loader("numrange", RangeAsStringLoader)
            connection.adapters.register_loader("tsrange", RangeAsStringLoader)
            connection.adapters.register_loader("tstzrange", RangeAsStringLoader)
            connection.adapters.register_loader("daterange", RangeAsStringLoader)

            with connection.cursor(name=f"posthog_{team_id}_{schema}.{table_name}") as cursor:
                query = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                logger.debug(f"Postgres query: {query.as_string()}")

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
        items=get_rows(chunk_size),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
    )
