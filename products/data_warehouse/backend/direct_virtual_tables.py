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
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    filter_dwh_columns_by_enabled_columns,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataSource


def eligible_direct_query_schemas(team_id: int, source_id: str) -> list[ExternalDataSchema]:
    """The synced schema rows a dual-mode connection exposes as live virtual tables.

    Single source of truth for both the build path (``_fetch_sources``) and the serialize
    catalog, so the two selections can't drift. Excludes rows without usable ``schema_metadata``
    (e.g. discovered before metadata persistence shipped) and rows with ``row_filters`` — a
    sync-time row restriction the live direct query can't reproduce, so exposing the upstream
    table would let a user read rows the schema was configured not to sync.
    """
    return [
        schema_row
        for schema_row in ExternalDataSchema.objects.filter(
            team_id=team_id,
            source_id=source_id,
            should_sync=True,
        )
        .exclude(deleted=True)
        # `table` is the synced S3 row backing the warehouse access-control check on the build path.
        .select_related("table")
        .order_by("name")
        if schema_row.schema_metadata and not schema_row.row_filters
    ]


def build_direct_table_for_schema(schema: "ExternalDataSchema", source: "ExternalDataSource") -> DirectSQLTable | None:
    """Build the live-query table for one schema row of a dual-mode source.

    Returns None when the source's engine is unknown or the schema row carries no usable
    column metadata (e.g. discovered before metadata persistence shipped).
    """
    metadata = schema.schema_metadata
    engine = source.direct_engine

    # Defense in depth for any direct caller: a row-filtered schema is already excluded from the
    # catalog by eligible_direct_query_schemas; never build a live table that would bypass it.
    if schema.row_filters:
        return None

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
