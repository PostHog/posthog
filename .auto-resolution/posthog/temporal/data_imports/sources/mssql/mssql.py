from __future__ import annotations

import math
import typing
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any

import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE, DEFAULT_TABLE_SIZE_BYTES
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from posthog.temporal.data_imports.sources.common.sql import Column, Table
from posthog.warehouse.types import IncrementalFieldType, PartitionSettings

if typing.TYPE_CHECKING:
    from pymssql import Cursor


def filter_mssql_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type in columns:
        type = type.lower()
        if type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif type == "datetime" or type == "datetime2" or type == "smalldatetime":
            results.append((column_name, IncrementalFieldType.DateTime))
        elif type == "tinyint" or type == "smallint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_schemas(
    host: str, user: str, password: str, database: str, schema: str, port: int
) -> dict[str, list[tuple[str, str]]]:
    # Importing pymssql requires mssql drivers to be installed locally - see posthog/warehouse/README.md
    import pymssql

    connection = pymssql.connect(
        server=host,
        # pymssql requires port to be str
        port=str(port),
        database=database,
        user=user,
        password=password,
        login_timeout=5,
    )

    with connection.cursor(as_dict=False) as cursor:
        cursor.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %(schema)s ORDER BY table_name ASC",
            {"schema": schema},
        )

        schema_list = collections.defaultdict(list)

        for row in cursor:
            if row:
                schema_list[row[0]].append((row[1], row[2]))

    connection.close()

    return schema_list


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    add_limit: bool = False,
) -> tuple[str, dict[str, Any]]:
    base_query = "SELECT {top} * FROM [{schema}].[{table_name}]"

    if not should_use_incremental_field:
        query = base_query.format(top="TOP 100" if add_limit else "", schema=schema, table_name=table_name)
        return query, {}

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    query = base_query.format(top="TOP 100" if add_limit else "", schema=schema, table_name=table_name)
    query = f"{query} WHERE [{incremental_field}] > %(incremental_value)s ORDER BY [{incremental_field}] ASC"

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


class MSSQLColumn(Column):
    """Implementation of the `Column` protocol for a MSSQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-types-transact-sql.
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

        match self.data_type:
            case "bigint":
                arrow_type = pa.int64()
            case "int" | "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "tinyint":
                arrow_type = pa.int8()
            case "decimal" | "numeric" | "money":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "float" | "real":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "nchar" | "nvarchar" | "ntext":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "datetime" | "datetime2" | "smalldatetime" | "datetimeoffset":
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

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _get_table(cursor: Cursor, schema: str, table_name: str) -> Table[MSSQLColumn]:
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

    numeric_data_types = {"numeric", "decimal", "money"}
    columns = []
    for row in cursor:
        if row is None:
            break

        name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate = row
        if data_type in numeric_data_types:
            numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
            numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
        else:
            numeric_precision = None
            numeric_scale = None

        columns.append(
            MSSQLColumn(
                name=name,
                data_type=data_type,
                nullable=nullable,
                numeric_precision=numeric_precision,
                numeric_scale=numeric_scale,
            )
        )

    if not columns:
        raise ValueError(f"Table {table_name} not found")

    return Table(
        name=table_name,
        parents=(schema,),
        columns=columns,
    )


def _get_table_average_row_size(
    cursor: Cursor,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> int | None:
    query, args = _build_query(
        schema,
        table_name,
        should_use_incremental_field,
        incremental_field,
        incremental_field_type,
        db_incremental_field_last_value,
        add_limit=True,
    )

    # Get column names from the table
    cursor.execute(
        f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %(schema)s AND TABLE_NAME = %(table)s ORDER BY ORDINAL_POSITION",
        {"schema": schema, "table": table_name},
    )
    rows = cursor.fetchall()
    if not rows:
        logger.debug(f"_get_table_average_row_size: No columns found.")
        return None

    columns = [row[0] for row in rows]

    # Build the DATALENGTH sum for each column
    datalength_sum = " + ".join(f"DATALENGTH([{col}])" for col in columns)

    size_query = f"""
        SELECT AVG({datalength_sum}) as avg_row_size
        FROM ({query}) as t
    """

    cursor.execute(size_query, args)
    row = cursor.fetchone()

    if row is None or row[0] is None:
        logger.debug(f"_get_table_average_row_size: No results returned.")
        return None

    row_size_bytes = max(row[0] or 0, 1)
    return row_size_bytes


def _get_table_chunk_size(
    cursor: Cursor,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    logger: FilteringBoundLogger,
) -> int:
    try:
        row_size_bytes = _get_table_average_row_size(
            cursor,
            schema,
            table_name,
            should_use_incremental_field,
            incremental_field,
            incremental_field_type,
            db_incremental_field_last_value,
            logger,
        )
        if row_size_bytes is None:
            logger.debug(
                f"_get_table_chunk_size: Could not calculate row size. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}"
            )
            return DEFAULT_CHUNK_SIZE
    except Exception as e:
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)
        capture_exception(e)
        return DEFAULT_CHUNK_SIZE

    chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)
    min_chunk_size = min(chunk_size, DEFAULT_CHUNK_SIZE)
    logger.debug(
        f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={min_chunk_size}"
    )
    return min_chunk_size


def _get_table_stats(cursor: Cursor, schema: str, table_name: str) -> tuple[int, float]:
    """Calculate the number of rows and size of a table.

    Uses sp_spaceused stored procedure which is the official way to get accurate table size and row count.
    Falls back to simpler version for SQL Server versions before 2012.
    """
    # Try modern version first (SQL Server 2012+)
    query = "EXEC sp_spaceused %(full_table_name)s, @updateusage = 'TRUE'"

    try:
        cursor.execute(query, {"full_table_name": f"[{schema}].[{table_name}]"})
    except Exception:
        # If @updateusage parameter fails, try the older version
        query = "EXEC sp_spaceused %(full_table_name)s"
        cursor.execute(query, {"full_table_name": f"[{schema}].[{table_name}]"})

    result = cursor.fetchone()
    if result is None:
        raise ValueError("_get_partition_settings: sp_spaceused returned no results")

    # sp_spaceused returns: name, rows, reserved, data, index_size, unused
    _, total_rows, _, data_size, _, _ = result

    # Convert string values to numbers
    total_rows = int(total_rows)

    # Parse size with unit (e.g. "1024.45 MB" -> 1024.45, "MB")
    size_parts = data_size.strip().split(" ")
    if len(size_parts) != 2:
        raise ValueError(
            f"_get_partition_settings: Invalid sp_spaceused result: expected 2 parts, got {len(size_parts)}"
        )

    size_value = float(size_parts[0])
    unit = size_parts[1].upper()

    # Convert to bytes based on unit
    multiplier = {"KB": 1024, "MB": 1024 * 1024, "GB": 1024 * 1024 * 1024, "TB": 1024 * 1024 * 1024 * 1024}.get(unit)
    if multiplier is None:
        raise ValueError(f"_get_partition_settings: Unexpected unit '{unit}' in sp_spaceused result")

    total_bytes = size_value * multiplier
    return total_rows, total_bytes


def _get_rows_to_sync(
    cursor: Cursor, inner_query: str, inner_query_args: dict[str, Any], logger: FilteringBoundLogger
) -> int:
    try:
        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

        cursor.execute(query, inner_query_args)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)

        return 0


def _get_partition_settings(
    cursor: Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    """Calculate the partition size and count for a table."""

    total_rows, total_bytes = _get_table_stats(cursor, schema, table_name)
    if total_bytes == 0 or total_rows == 0:
        return None

    # Calculate partition size based on target bytes per partition
    bytes_per_row = total_bytes / total_rows
    partition_size = int(round(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / bytes_per_row))
    partition_count = math.floor(total_rows / partition_size)
    logger.debug(
        f"_get_partition_settings: {total_rows=}, {total_bytes=}, {bytes_per_row=}, "
        f"{partition_size=}, {partition_count=}"
    )

    if partition_count == 0:
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


def mssql_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    import pymssql

    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with tunnel() as (host, port):
        with pymssql.connect(
            server=host,
            port=str(port),
            database=database,
            user=user,
            password=password,
            login_timeout=5,
        ) as connection:
            with connection.cursor() as cursor:
                inner_query, inner_query_args = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )

                primary_keys = _get_primary_keys(cursor, schema, table_name)
                table = _get_table(cursor, schema, table_name)
                rows_to_sync = _get_rows_to_sync(cursor, inner_query, inner_query_args, logger)
                chunk_size = _get_table_chunk_size(
                    cursor,
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    logger,
                )
                try:
                    partition_settings = (
                        _get_partition_settings(cursor, schema, table_name, logger)
                        if should_use_incremental_field
                        else None
                    )
                except Exception as e:
                    logger.debug(f"_get_partition_settings: Error: {e}. Skipping partitioning.")
                    capture_exception(e)
                    partition_settings = None

                # Fallback on checking for an `id` field on the table
                if primary_keys is None and "id" in table:
                    primary_keys = ["id"]

    def get_rows() -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()

        with tunnel() as (host, port):
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
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                    )
                    logger.debug(f"MS SQL query: {query.format(args)}")

                    cursor.execute(query, args)

                    column_names = [column[0] for column in cursor.description or []]

                    while True:
                        rows = cursor.fetchmany(chunk_size)
                        if not rows:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
    )
