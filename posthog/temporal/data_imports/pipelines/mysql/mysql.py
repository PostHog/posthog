import dataclasses
from typing import Any, Optional
from collections.abc import Iterator
from django.conf import settings
import pyarrow as pa
import pymysql
from pymysql.cursors import SSCursor, Cursor

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


def _sanitize_identifier(identifier: str) -> str:
    if not identifier.isidentifier():
        if identifier.startswith("$") or (len(identifier) > 0 and identifier[0].isdigit()):
            if not identifier[1:].replace(".", "").replace("_", "").replace("-", "").isidentifier():
                raise ValueError(f"Invalid SQL identifier: {identifier}")

    if not identifier.replace(".", "").replace("_", "").replace("-", "").replace("$", "").isalnum():
        raise ValueError(f"Invalid SQL identifier: {identifier}")

    return f"`{identifier}`"


def _build_query(
    schema: str,
    table_name: str,
    is_incremental: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> tuple[str, dict[str, Any]]:
    query = f"SELECT * FROM `{schema}`.`{table_name}`"

    if not is_incremental:
        return query, {}

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = f"SELECT * FROM {_sanitize_identifier(schema)}.{_sanitize_identifier(table_name)} WHERE {_sanitize_identifier(incremental_field)} >= %(incremental_value)s ORDER BY {_sanitize_identifier(incremental_field)} ASC"

    return query, {
        "incremental_value": db_incremental_field_last_value,
    }


def _get_primary_keys(cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
    query = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %(schema)s
        AND TABLE_NAME = %(table_name)s
        AND COLUMN_KEY = 'PRI'"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
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


def _get_table_structure(cursor: Cursor, schema: str, table_name: str) -> list[TableStructureRow]:
    query = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            numeric_precision,
            numeric_scale
        FROM
            information_schema.columns
        WHERE
            table_schema = %(schema)s
            AND table_name = %(table_name)s"""

    cursor.execute(
        query,
        {
            "schema": schema,
            "table_name": table_name,
        },
    )
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
        mysql_type = col.data_type

        arrow_type: pa.DataType

        # Map MySQL type names to PyArrow types
        match mysql_type:
            case "bigint":
                arrow_type = pa.int64()
            case "int" | "integer" | "mediumint":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "tinyint":
                arrow_type = pa.int8()
            case "decimal" | "numeric":
                precision = col.numeric_precision if col.numeric_precision is not None else DEFAULT_NUMERIC_PRECISION
                scale = col.numeric_scale if col.numeric_scale is not None else DEFAULT_NUMERIC_SCALE

                arrow_type = build_pyarrow_decimal_type(precision, scale)
            case "float":
                arrow_type = pa.float32()
            case "double" | "double precision":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "mediumtext" | "longtext":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "datetime" | "timestamp":
                arrow_type = pa.timestamp("us")
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
            case _ if mysql_type.endswith("[]"):  # Array types (though not native in MySQL)
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        fields.append(pa.field(name, arrow_type, nullable=col.is_nullable))

    return pa.schema(fields)


def mysql_source(
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
    using_ssl: bool,
    schema: str,
    table_names: list[str],
    is_incremental: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    ssl_ca: str | None = None

    if using_ssl:
        ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

    with pymysql.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        connect_timeout=5,
        ssl_ca=ssl_ca,
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

        with pymysql.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=5,
            ssl_ca=ssl_ca,
        ) as connection:
            with connection.cursor(SSCursor) as cursor:
                query, args = _build_query(
                    schema,
                    table_name,
                    is_incremental,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                logger.debug(f"MySQL query: {query.format(args)}")

                cursor.execute(query, args)

                column_names = [column[0] for column in cursor.description or []]

                while True:
                    rows = cursor.fetchmany(DEFAULT_CHUNK_SIZE)
                    if not rows:
                        break

                    yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(name=name, items=get_rows(), primary_keys=primary_keys)
