from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pymssql
from dlt.common.normalizers.naming.snake_case import NamingConvention
from pymssql import Cursor

from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
)
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.pipelines.sql_database.settings import (
    DEFAULT_CHUNK_SIZE,
)
from posthog.warehouse.models import IncrementalFieldType


def _build_query(
    schema: str,
    table_name: str,
    is_incremental: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
) -> tuple[str, dict[str, Any]]:
    query = f"SELECT * FROM [{schema}].[{table_name}]"

    if not is_incremental:
        return query, {}

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = f"SELECT * FROM [{schema}].[{table_name}] WHERE [{incremental_field}] > %(incremental_value)s ORDER BY [{incremental_field}] ASC"

    return query, {
        "incremental_value": db_incremental_field_last_value,
    }


def _get_primary_keys(cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
    query = """
        SELECT c.name AS column_name
        FROM sys.indexes i
        JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
        JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
        JOIN sys.tables t ON i.object_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE i.is_primary_key = 1
        AND s.name = %(schema)s
        AND t.name = %(table_name)s
        ORDER BY ic.key_ordinal"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
    rows = cursor.fetchall()
    if not rows:
        return None

    return [row[0] for row in rows]


@dataclass
class TableStructureRow:
    column_name: str
    data_type: str
    is_nullable: bool
    numeric_precision: int | None
    numeric_scale: int | None


def _get_table_structure(cursor: Cursor, schema: str, table_name: str) -> list[TableStructureRow]:
    query = """
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            CASE IS_NULLABLE WHEN 'YES' THEN 1 ELSE 0 END as IS_NULLABLE,
            NUMERIC_PRECISION,
            NUMERIC_SCALE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %(schema)s
        AND TABLE_NAME = %(table_name)s
        ORDER BY ORDINAL_POSITION"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
    rows = cursor.fetchall()
    if not rows:
        raise ValueError(f"Table {table_name} not found")
    return [
        TableStructureRow(
            column_name=row[0],
            data_type=row[1],
            is_nullable=bool(row[2]),
            numeric_precision=row[3],
            numeric_scale=row[4],
        )
        for row in rows
    ]


def _get_arrow_schema(table_structure: list[TableStructureRow]) -> pa.Schema:
    fields = []

    for col in table_structure:
        name = col.column_name
        data_type = col.data_type.lower()

        arrow_type: pa.DataType

        # Map MS SQL type names to PyArrow types
        # https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-types-transact-sql?view=sql-server-ver16
        match data_type:
            case "bigint":
                arrow_type = pa.int64()
            case "int" | "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "tinyint":
                arrow_type = pa.int8()
            case "decimal" | "numeric" | "money":
                precision = col.numeric_precision if col.numeric_precision is not None else DEFAULT_NUMERIC_PRECISION
                scale = col.numeric_scale if col.numeric_scale is not None else DEFAULT_NUMERIC_SCALE
                arrow_type = build_pyarrow_decimal_type(precision, scale)
            case "float" | "real":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "nchar" | "nvarchar" | "ntext":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "datetime" | "datetime2" | "smalldatetime":
                arrow_type = pa.timestamp("us")
            case "time":
                arrow_type = pa.time64("us")
            case "bit" | "boolean" | "bool":
                arrow_type = pa.bool_()
            case "binary" | "varbinary" | "image":
                arrow_type = pa.binary()
            case "json":
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        fields.append(pa.field(name, arrow_type, nullable=col.is_nullable))

    return pa.schema(fields)


def mssql_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    schema: str,
    table_names: list[str],
    is_incremental: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with pymssql.connect(
        server=host,
        port=str(port),
        database=database,
        user=user,
        password=password,
        login_timeout=5,
    ) as connection:
        with connection.cursor() as cursor:
            primary_keys = _get_primary_keys(cursor, schema, table_name)
            table_structure = _get_table_structure(cursor, schema, table_name)

            # Fallback on checking for an `id` field on the table
            if primary_keys is None:
                if any(ts.column_name == "id" for ts in table_structure):
                    primary_keys = ["id"]

    def get_rows() -> Iterator[Any]:
        arrow_schema = _get_arrow_schema(table_structure)

        with pymssql.connect(
            server=host,
            port=str(port),
            database=database,
            user=user,
            password=password,
            login_timeout=5,
        ) as connection:
            with connection.cursor() as cursor:
                query, args = _build_query(
                    schema,
                    table_name,
                    is_incremental,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                logger.debug(f"MS SQL query: {query.format(args)}")

                cursor.execute(query, args)

                column_names = [column[0] for column in cursor.description or []]

                while True:
                    rows = cursor.fetchmany(DEFAULT_CHUNK_SIZE)
                    if not rows:
                        break

                    yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=primary_keys,
    )
