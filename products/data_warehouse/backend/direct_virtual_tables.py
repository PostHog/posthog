"""Virtual direct-query tables for synced (dual-mode) sources.

A synced SQL source with ``direct_query_enabled`` has no physical ``DataWarehouseTable``
rows for its live tables — its physical rows are the synced S3 copies, which are
deliberately excluded from the direct catalog. This builds the same ``DirectSQLTable``
objects the pure-direct path derives from physical rows, but from each
``ExternalDataSchema``'s persisted ``schema_metadata`` instead.
"""

from typing import TYPE_CHECKING

from posthog.hogql.database.direct_mysql_table import DirectMySQLTable
from posthog.hogql.database.direct_postgres_table import DirectPostgresTable
from posthog.hogql.database.direct_snowflake_table import DirectSnowflakeTable
from posthog.hogql.database.direct_sql_table import DirectSQLTable

from products.data_warehouse.backend.mysql_helpers import (
    get_default_mysql_schema,
    get_mysql_source_location,
    mysql_schema_metadata_to_dwh_columns,
)
from products.data_warehouse.backend.postgres_helpers import (
    get_postgres_source_location,
    postgres_schema_metadata_to_dwh_columns,
)
from products.data_warehouse.backend.snowflake_helpers import (
    get_default_snowflake_catalog,
    get_default_snowflake_schema,
    get_snowflake_source_location,
    snowflake_schema_metadata_to_dwh_columns,
)
from products.warehouse_sources.backend.facade.hogql import hogql_fields_and_structure_for_columns
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    filter_dwh_columns_by_enabled_columns,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource


def build_direct_table_for_schema(schema: "ExternalDataSchema", source: "ExternalDataSource") -> DirectSQLTable | None:
    """Build the live-query table for one schema row of a dual-mode source.

    Returns None when the source's engine is unknown or the schema row carries no usable
    column metadata (e.g. discovered before metadata persistence shipped).
    """
    metadata = schema.schema_metadata
    engine = source.direct_engine

    if engine == "postgres":
        columns = postgres_schema_metadata_to_dwh_columns(metadata)
        if not columns:
            return None
        columns = filter_dwh_columns_by_enabled_columns(
            columns,
            schema.enabled_columns,
            schema.primary_key_columns,
            schema.incremental_field,
            # Direct-postgres columns are keyed by raw, case-sensitive source names.
            normalize=False,
        )
        fields, _ = hogql_fields_and_structure_for_columns(columns)
        catalog, postgres_schema, table_name = get_postgres_source_location(
            schema_name=schema.name,
            schema_metadata=metadata,
            default_schema=(source.job_inputs or {}).get("schema"),
        )
        return DirectPostgresTable(
            name=schema.name,
            fields=fields,
            postgres_catalog=catalog,
            postgres_schema=postgres_schema,
            postgres_table_name=table_name,
            external_data_source_id=str(source.id),
            connection_metadata=source.connection_metadata,
        )

    if engine == "mysql":
        columns = mysql_schema_metadata_to_dwh_columns(metadata)
        if not columns:
            return None
        columns = filter_dwh_columns_by_enabled_columns(
            columns,
            schema.enabled_columns,
            schema.primary_key_columns,
            schema.incremental_field,
            # Direct-mysql columns are keyed by raw, case-sensitive source names.
            normalize=False,
        )
        fields, _ = hogql_fields_and_structure_for_columns(columns)
        mysql_schema, table_name = get_mysql_source_location(
            schema_name=schema.name,
            schema_metadata=metadata,
            default_schema=get_default_mysql_schema(source),
        )
        return DirectMySQLTable(
            name=schema.name,
            fields=fields,
            mysql_schema=mysql_schema,
            mysql_table_name=table_name,
            external_data_source_id=str(source.id),
            connection_metadata=source.connection_metadata,
        )

    if engine == "snowflake":
        columns = snowflake_schema_metadata_to_dwh_columns(metadata)
        if not columns:
            return None
        columns = filter_dwh_columns_by_enabled_columns(
            columns,
            schema.enabled_columns,
            schema.primary_key_columns,
            schema.incremental_field,
            # Direct-snowflake columns are keyed by raw, case-sensitive source names.
            normalize=False,
        )
        fields, _ = hogql_fields_and_structure_for_columns(columns)
        catalog, snowflake_schema, table_name = get_snowflake_source_location(
            schema_name=schema.name,
            schema_metadata=metadata,
            default_catalog=get_default_snowflake_catalog(source),
            default_schema=get_default_snowflake_schema(source),
        )
        return DirectSnowflakeTable(
            name=schema.name,
            fields=fields,
            snowflake_catalog=catalog,
            snowflake_schema=snowflake_schema,
            snowflake_table_name=table_name,
            external_data_source_id=str(source.id),
            connection_metadata=source.connection_metadata,
        )

    return None
