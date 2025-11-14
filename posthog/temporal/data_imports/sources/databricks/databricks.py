import collections
from collections.abc import Iterator
from typing import Any, Optional

from databricks import sql
from databricks.sql.client import Connection, Cursor
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.generated_configs import DatabricksSourceConfig

from products.data_warehouse.backend.types import IncrementalFieldType


def filter_databricks_incremental_fields(columns: list[tuple[str, str]]) -> list[tuple[str, IncrementalFieldType]]:
    """Filter columns to return only those that can be used for incremental syncing."""
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, col_type in columns:
        col_type = col_type.lower()
        if col_type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp))
        elif col_type == "date":
            results.append((column_name, IncrementalFieldType.Date))
        elif col_type in ("int", "bigint", "smallint", "tinyint", "long"):
            results.append((column_name, IncrementalFieldType.Integer))

    return results


def get_schemas(config: DatabricksSourceConfig) -> dict[str, list[tuple[str, str]]]:
    """Get all tables and their columns from the specified Databricks catalog and schema."""
    with _get_connection(config.server_hostname, config.http_path, config.access_token) as connection:
        with connection.cursor() as cursor:
            if cursor is None:
                raise Exception("Can't create cursor to Databricks")

            # Get all tables in the specified catalog.schema
            cursor.tables(catalog_name=config.catalog, schema_name=config.schema)
            tables = cursor.fetchall()

            schema_list = collections.defaultdict(list)

            # For each table, get its columns
            for table_row in tables:
                table_name = table_row[2]  # TABLE_NAME is at index 2

                # Get columns for this table
                cursor.execute(
                    f"DESCRIBE TABLE `{config.catalog}`.`{config.schema}`.`{table_name}`"
                )
                columns = cursor.fetchall()

                for col_row in columns:
                    col_name = col_row[0]
                    col_type = col_row[1]
                    schema_list[table_name].append((col_name, col_type))

    return schema_list


def _get_connection(server_hostname: str, http_path: str, access_token: str) -> Connection:
    """Create a connection to Databricks SQL warehouse."""
    return sql.connect(
        server_hostname=server_hostname,
        http_path=http_path,
        access_token=access_token,
    )


def _build_query(
    catalog: str,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
) -> str:
    """Build SQL query for fetching data from Databricks table."""
    full_table_name = f"`{catalog}`.`{schema}`.`{table_name}`"

    if not should_use_incremental_field:
        return f"SELECT * FROM {full_table_name}"

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    # Format the incremental value based on type
    if incremental_field_type in (IncrementalFieldType.DateTime, IncrementalFieldType.Timestamp):
        formatted_value = f"'{db_incremental_field_last_value}'"
    elif incremental_field_type == IncrementalFieldType.Date:
        formatted_value = f"'{db_incremental_field_last_value}'"
    else:
        formatted_value = str(db_incremental_field_last_value)

    return f"SELECT * FROM {full_table_name} WHERE `{incremental_field}` >= {formatted_value} ORDER BY `{incremental_field}` ASC"


def _get_rows_to_sync(
    cursor: Cursor, inner_query: str, logger: FilteringBoundLogger
) -> int:
    """Get count of rows that will be synced."""
    try:
        query = f"SELECT COUNT(*) FROM ({inner_query}) as t"
        cursor.execute(query)
        row = cursor.fetchone()

        if row is None:
            logger.debug("_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return rows_to_sync_int
    except Exception as e:
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
        capture_exception(e)
        return 0


def _get_primary_keys(cursor: Cursor, catalog: str, schema: str, table_name: str) -> list[str] | None:
    """Get primary keys for a Databricks table."""
    try:
        # Query information schema for primary keys
        query = f"""
        SELECT column_name
        FROM `{catalog}`.information_schema.constraint_column_usage
        WHERE table_catalog = '{catalog}'
          AND table_schema = '{schema}'
          AND table_name = '{table_name}'
          AND constraint_name LIKE 'PRIMARY%'
        """
        cursor.execute(query)
        keys = [row[0] for row in cursor.fetchall()]
        return keys if len(keys) > 0 else None
    except Exception:
        # If we can't get primary keys from information schema, return None
        # This is okay - the table just won't have merge keys defined
        return None


def databricks_source(
    server_hostname: str,
    http_path: str,
    access_token: str,
    catalog: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> SourceResponse:
    """Create a Databricks source for the data pipeline."""
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    with _get_connection(server_hostname, http_path, access_token) as connection:
        with connection.cursor() as cursor:
            inner_query = _build_query(
                catalog,
                schema,
                table_name,
                should_use_incremental_field,
                incremental_field,
                incremental_field_type,
                db_incremental_field_last_value,
            )
            primary_keys = _get_primary_keys(cursor, catalog, schema, table_name)
            rows_to_sync = _get_rows_to_sync(cursor, inner_query, logger)

    def get_rows() -> Iterator[Any]:
        with _get_connection(server_hostname, http_path, access_token) as connection:
            with connection.cursor() as cursor:
                query = _build_query(
                    catalog,
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                )
                logger.debug(f"Databricks query: {query}")
                cursor.execute(query)

                # Fetch results in batches using arrow format
                while True:
                    arrow_table = cursor.fetchmany_arrow(5000)
                    if arrow_table is None or len(arrow_table) == 0:
                        break
                    yield arrow_table

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(name=name, items=get_rows, primary_keys=primary_keys, rows_to_sync=rows_to_sync)
