from __future__ import annotations

import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any, Optional

import clickhouse_connect
import pyarrow as pa
from clickhouse_connect.driver import Client
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.consts import DEFAULT_CHUNK_SIZE
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    table_from_iterator,
)

from products.data_warehouse.backend.types import IncrementalFieldType


# Map ClickHouse types to IncrementalFieldType
CLICKHOUSE_TYPE_MAPPING = {
    "Int8": IncrementalFieldType.Integer,
    "Int16": IncrementalFieldType.Integer,
    "Int32": IncrementalFieldType.Integer,
    "Int64": IncrementalFieldType.Integer,
    "UInt8": IncrementalFieldType.Integer,
    "UInt16": IncrementalFieldType.Integer,
    "UInt32": IncrementalFieldType.Integer,
    "UInt64": IncrementalFieldType.Integer,
    "Date": IncrementalFieldType.Date,
    "Date32": IncrementalFieldType.Date,
    "DateTime": IncrementalFieldType.DateTime,
    "DateTime64": IncrementalFieldType.DateTime,
}


def filter_clickhouse_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    """Filter columns that can be used for incremental syncing."""
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, type_str in columns:
        # Handle Nullable types
        base_type = type_str.replace("Nullable(", "").replace(")", "").strip()

        # Check if the base type is in our mapping
        for ch_type, incr_type in CLICKHOUSE_TYPE_MAPPING.items():
            if base_type.startswith(ch_type):
                results.append((column_name, incr_type))
                break

    return results


def get_clickhouse_schemas(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    secure: bool = False,
) -> dict[str, list[tuple[str, str]]]:
    """Get all tables and their columns from ClickHouse database."""

    client = clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
        secure=secure,
        connect_timeout=10,
    )

    try:
        # Query to get all tables and their columns
        query = """
        SELECT
            table AS table_name,
            name AS column_name,
            type AS data_type
        FROM system.columns
        WHERE database = %(database)s
        AND table NOT LIKE '.%'
        ORDER BY table_name ASC, position ASC
        """

        result = client.query(query, parameters={"database": database})

        schema_list = collections.defaultdict(list)
        for row in result.result_rows:
            table_name, column_name, data_type = row
            schema_list[table_name].append((column_name, data_type))

        return dict(schema_list)
    finally:
        client.close()


def get_clickhouse_row_count(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    secure: bool = False,
) -> dict[str, int]:
    """Get row counts for all tables in the database."""

    client = clickhouse_connect.get_client(
        host=host,
        port=port,
        username=user,
        password=password,
        database=database,
        secure=secure,
        connect_timeout=10,
    )

    try:
        # Get list of tables
        query = """
        SELECT DISTINCT table
        FROM system.columns
        WHERE database = %(database)s
        AND table NOT LIKE '.%'
        """

        result = client.query(query, parameters={"database": database})
        tables = [row[0] for row in result.result_rows]

        if not tables:
            return {}

        row_counts = {}
        for table in tables:
            try:
                count_query = f"SELECT count() FROM `{database}`.`{table}`"
                count_result = client.query(count_query, settings={"max_execution_time": 30})
                row_counts[table] = count_result.result_rows[0][0] if count_result.result_rows else 0
            except:
                # If count fails for a table, skip it
                continue

        return row_counts
    except:
        return {}
    finally:
        client.close()


def clickhouse_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    secure: bool,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    """Create a ClickHouse source for data import."""

    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    chunk_size = chunk_size_override or DEFAULT_CHUNK_SIZE

    with tunnel() as (host, port):
        client = clickhouse_connect.get_client(
            host=host,
            port=port,
            username=user,
            password=password,
            database=database,
            secure=secure,
            connect_timeout=10,
        )

        try:
            # Build the query
            if should_use_incremental_field:
                if incremental_field is None or incremental_field_type is None:
                    raise ValueError("incremental_field and incremental_field_type can't be None")

                if db_incremental_field_last_value is None:
                    db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

                query = f"""
                SELECT * FROM `{database}`.`{table_name}`
                WHERE `{incremental_field}` >= %(last_value)s
                ORDER BY `{incremental_field}` ASC
                """
                params = {"last_value": db_incremental_field_last_value}
            else:
                query = f"SELECT * FROM `{database}`.`{table_name}`"
                params = {}

            logger.info(f"Executing ClickHouse query: {query}")

            # Get schema information
            schema_query = f"""
            SELECT name, type
            FROM system.columns
            WHERE database = %(database)s AND table = %(table)s
            ORDER BY position ASC
            """
            schema_result = client.query(schema_query, parameters={"database": database, "table": table_name})
            columns = [(row[0], row[1]) for row in schema_result.result_rows]

            # Build PyArrow schema
            pa_schema = _build_pyarrow_schema(columns)

            # Define the row iterator
            def row_iterator() -> Iterator[pa.Table]:
                query_result = client.query(query, parameters=params, settings={"max_block_size": chunk_size})

                # Convert to PyArrow Table
                rows = query_result.result_rows
                if rows:
                    # Convert rows to dict format
                    col_names = [col[0] for col in columns]
                    data_dict = {col_name: [] for col_name in col_names}

                    for row in rows:
                        for i, col_name in enumerate(col_names):
                            data_dict[col_name].append(row[i])

                    # Create PyArrow arrays
                    arrays = []
                    for col_name in col_names:
                        arrays.append(pa.array(data_dict[col_name]))

                    table = pa.Table.from_arrays(arrays, schema=pa_schema)
                    yield table

            # Determine primary keys and partition settings
            primary_keys = _get_primary_keys(client, database, table_name)

            # Build partition settings
            partition_mode = None
            partition_keys = None
            partition_format = None

            if incremental_field and incremental_field_type:
                if incremental_field_type == IncrementalFieldType.DateTime or incremental_field_type == IncrementalFieldType.Date:
                    partition_mode = "datetime"
                    partition_keys = [incremental_field]
                    partition_format = "month"
                elif incremental_field_type == IncrementalFieldType.Integer:
                    partition_mode = "numerical"
                    partition_keys = [incremental_field]

            return SourceResponse(
                items=row_iterator(),
                schema=pa_schema,
                primary_keys=primary_keys,
                partition_mode=partition_mode,
                partition_keys=partition_keys,
                partition_format=partition_format,
            )
        finally:
            client.close()


def _build_pyarrow_schema(columns: list[tuple[str, str]]) -> pa.Schema:
    """Build a PyArrow schema from ClickHouse column definitions."""
    fields = []

    for col_name, col_type in columns:
        pa_type = _clickhouse_type_to_pyarrow(col_type)
        fields.append(pa.field(col_name, pa_type))

    return pa.schema(fields)


def _clickhouse_type_to_pyarrow(ch_type: str) -> pa.DataType:
    """Convert ClickHouse type to PyArrow type."""
    # Handle Nullable types
    is_nullable = ch_type.startswith("Nullable(")
    if is_nullable:
        ch_type = ch_type.replace("Nullable(", "").replace(")", "").strip()

    # Map basic types
    if ch_type.startswith("String") or ch_type.startswith("FixedString"):
        return pa.string()
    elif ch_type == "Int8":
        return pa.int8()
    elif ch_type == "Int16":
        return pa.int16()
    elif ch_type == "Int32":
        return pa.int32()
    elif ch_type == "Int64":
        return pa.int64()
    elif ch_type == "UInt8":
        return pa.uint8()
    elif ch_type == "UInt16":
        return pa.uint16()
    elif ch_type == "UInt32":
        return pa.uint32()
    elif ch_type == "UInt64":
        return pa.uint64()
    elif ch_type == "Float32":
        return pa.float32()
    elif ch_type == "Float64":
        return pa.float64()
    elif ch_type == "Date" or ch_type == "Date32":
        return pa.date32()
    elif ch_type.startswith("DateTime"):
        return pa.timestamp("s")
    elif ch_type.startswith("Decimal"):
        return pa.decimal128(38, 10)  # Default precision/scale
    elif ch_type.startswith("Array"):
        # For arrays, default to string representation
        return pa.string()
    elif ch_type == "Bool":
        return pa.bool_()
    else:
        # Default to string for unknown types
        return pa.string()


def _get_primary_keys(client: Client, database: str, table_name: str) -> list[str]:
    """Get primary keys for a ClickHouse table."""
    try:
        query = """
        SELECT primary_key
        FROM system.tables
        WHERE database = %(database)s AND name = %(table)s
        """
        result = client.query(query, parameters={"database": database, "table": table_name})

        if result.result_rows and result.result_rows[0][0]:
            # Parse the primary key string (e.g., "id" or "id, timestamp")
            pk_string = result.result_rows[0][0]
            primary_keys = [key.strip() for key in pk_string.split(",")]
            return primary_keys

        # If no primary key, try to use the first column as a fallback
        schema_query = """
        SELECT name
        FROM system.columns
        WHERE database = %(database)s AND table = %(table)s
        ORDER BY position ASC
        LIMIT 1
        """
        schema_result = client.query(schema_query, parameters={"database": database, "table": table_name})
        if schema_result.result_rows:
            return [schema_result.result_rows[0][0]]

        return []
    except:
        return []
