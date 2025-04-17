import dataclasses
import math
from collections.abc import Iterator
from typing import Any, Optional

import psycopg
import psycopg.rows
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
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.pipelines.sql_database.settings import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.warehouse.models import IncrementalFieldType
from posthog.warehouse.types import PartitionSettings


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


def _build_query(
    schema: str,
    table_name: str,
    is_incremental: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> sql.Composed:
    query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(schema, table_name))

    if not is_incremental:
        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = sql.SQL(
        "SELECT * FROM {schema}.{table} WHERE {incremental_field} >= {last_value} ORDER BY {incremental_field} ASC"
    ).format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        last_value=sql.Literal(db_incremental_field_last_value),
    )

    return query


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


def _get_table_chunk_size(cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger) -> int:
    try:
        query = sql.SQL("""
            SELECT SUM(pg_column_size(t.*)) / COUNT(t.*) FROM (
                SELECT * FROM {}
                LIMIT 100
            ) as t
        """).format(sql.Identifier(schema, table_name))

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
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


@dataclasses.dataclass
class TableStructureRow:
    column_name: str
    data_type: str
    is_nullable: bool
    numeric_precision: Optional[int]
    numeric_scale: Optional[int]


def _get_partition_settings(cursor: psycopg.Cursor, schema: str, table_name: str) -> PartitionSettings | None:
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
    except Exception as e:
        capture_exception(e)
        return None

    result = cursor.fetchone()

    if result is None or len(result) == 0 or result[0] is None:
        return None

    partition_size = int(result[0])
    total_rows = int(result[1])
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def _get_table_structure(cursor: psycopg.Cursor, schema: str, table_name: str) -> list[TableStructureRow]:
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
    rows = cursor.fetchall()
    return [
        TableStructureRow(
            column_name=row[0], data_type=row[1], is_nullable=row[2], numeric_precision=row[3], numeric_scale=row[4]
        )
        for row in rows
    ]


def _get_arrow_schema_from_type_name(table_structure: list[TableStructureRow]) -> pa.Schema:
    fields = []

    for col in table_structure:
        name = col.column_name
        pg_type = col.data_type

        arrow_type: pa.DataType

        # Map PostgreSQL type names to PyArrow types
        match pg_type:
            case "bigint":
                arrow_type = pa.int64()
            case "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                precision = col.numeric_precision if col.numeric_precision is not None else DEFAULT_NUMERIC_PRECISION
                scale = col.numeric_scale if col.numeric_scale is not None else DEFAULT_NUMERIC_SCALE

                arrow_type = build_pyarrow_decimal_type(precision, scale)
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
            case _ if pg_type.endswith("[]"):  # Array types
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        fields.append(pa.field(name, arrow_type, nullable=col.is_nullable))

    return pa.schema(fields)


def postgres_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    is_incremental: bool,
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
            primary_keys = _get_primary_keys(cursor, schema, table_name)
            table_structure = _get_table_structure(cursor, schema, table_name)
            chunk_size = _get_table_chunk_size(cursor, schema, table_name, logger)
            partition_settings = _get_partition_settings(cursor, schema, table_name) if is_incremental else None

            # Falback on checking for an `id` field on the table
            if primary_keys is None:
                if any(ts.column_name == "id" for ts in table_structure):
                    primary_keys = ["id"]

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = _get_arrow_schema_from_type_name(table_structure)

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

            with connection.cursor(name=f"posthog_{team_id}_{schema}.{table_name}") as cursor:
                query = _build_query(
                    schema,
                    table_name,
                    is_incremental,
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
    )
