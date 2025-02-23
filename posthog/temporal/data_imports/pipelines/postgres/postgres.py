import dataclasses
from typing import Any, Optional
from collections.abc import Iterator
import psycopg.rows
import pyarrow as pa
import psycopg
from psycopg import sql

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.pipelines.sql_database.settings import DEFAULT_CHUNK_SIZE
from posthog.warehouse.models import IncrementalFieldType

from dlt.common.normalizers.naming.snake_case import NamingConvention


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


@dataclasses.dataclass
class TableStructureRow:
    column_name: str
    data_type: str
    is_nullable: bool
    numeric_precision: Optional[int]
    numeric_scale: Optional[int]


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

            # Falback on checking for an `id` field on the table
            if primary_keys is None:
                if any(ts.column_name == "id" for ts in table_structure):
                    primary_keys = ["id"]

    def get_rows() -> Iterator[Any]:
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
                    rows = cursor.fetchmany(DEFAULT_CHUNK_SIZE)
                    if not rows:
                        break

                    yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(name=name, items=get_rows(), primary_keys=primary_keys)
