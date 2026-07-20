"""Engine-keyed adapters for SQL-source engine behaviour.

The presentation layer must not branch on source type. This behaviour varies by SQL *engine*
(postgres/mysql/snowflake/redshift), not by source type, and the same engine can back more than
one source type, so it dispatches here via ``source.direct_engine`` (``DIRECT_ENGINE_BY_SOURCE_TYPE``,
defined for every SQL source regardless of access method). Each adapter bundles the engine-specific
pieces of: building a live-query ``DataWarehouseTable`` (resolving the upstream location, mapping
columns, creating / reprojecting / hiding the row) and reconciling schema rows on refresh. Warehouse
-domain orchestration (filtering enabled columns, saving the row) stays in the view.
"""

from abc import ABC, abstractmethod
from typing import Any

from products.data_warehouse.backend.direct_mysql import hide_direct_mysql_table, upsert_direct_mysql_table
from products.data_warehouse.backend.direct_postgres import hide_direct_postgres_table, upsert_direct_postgres_table
from products.data_warehouse.backend.direct_redshift import hide_direct_redshift_table, upsert_direct_redshift_table
from products.data_warehouse.backend.direct_snowflake import hide_direct_snowflake_table, upsert_direct_snowflake_table
from products.data_warehouse.backend.mysql_helpers import (
    get_mysql_source_location,
    reconcile_mysql_schemas,
    reproject_direct_mysql_table,
)
from products.data_warehouse.backend.postgres_helpers import (
    get_postgres_source_location,
    reconcile_postgres_schemas,
    reproject_direct_postgres_table,
)
from products.data_warehouse.backend.postgres_warehouse_migration import reconcile_refresh_name_substitutions
from products.data_warehouse.backend.redshift_helpers import (
    get_redshift_source_location,
    reconcile_redshift_schemas,
    reproject_direct_redshift_table,
)
from products.data_warehouse.backend.snowflake_helpers import (
    reconcile_snowflake_schemas,
    reproject_direct_snowflake_table,
)
from products.warehouse_sources.backend.facade.api import (
    mysql_columns_to_dwh_columns,
    postgres_columns_to_dwh_columns,
    snowflake_columns_to_dwh_columns,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSource

# `source_schema` is a warehouse_sources SourceSchema, the DWH table / column types are
# engine-specific unions; kept as `Any` at this boundary so the adapter stays a thin dispatcher.
SourceTableLocation = tuple[str | None, str, str]


def _location_metadata(source_schema: Any) -> dict[str, Any]:
    return {
        "source_catalog": source_schema.source_catalog if source_schema else None,
        "source_schema": source_schema.source_schema if source_schema else None,
        "source_table_name": source_schema.source_table_name if source_schema else None,
    }


class DirectQueryEngine(ABC):
    """One SQL engine's direct-query materialization ops. Registered by engine name."""

    engine: str
    # Postgres resolves its upstream `(catalog, schema, table)` location even in warehouse mode;
    # the other engines only need it in direct mode. Keeps the view off a source-type check.
    resolves_location_in_warehouse_mode: bool = False

    @abstractmethod
    def source_table_location(
        self,
        *,
        schema_name: str,
        source_schema: Any,
        default_schema: str | None,
        default_catalog: str | None = None,
    ) -> SourceTableLocation:
        """Resolve `(catalog, schema, table)` for a row. `catalog` is None for catalog-less engines."""
        raise NotImplementedError()

    @abstractmethod
    def columns_to_dwh_columns(self, source_columns: list[Any]) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def upsert_table(
        self,
        existing_table: Any,
        *,
        schema_name: str,
        source: ExternalDataSource,
        columns: Any,
        source_catalog: str | None,
        source_schema: str,
        source_table_name: str,
    ) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def reproject_table(self, schema_row: Any, *, source: ExternalDataSource, enabled_columns: list[str] | None) -> Any:
        raise NotImplementedError()

    @abstractmethod
    def hide_table(self, table: Any) -> None:
        raise NotImplementedError()

    @abstractmethod
    def reconcile_schemas(self, *, source: Any, source_schemas: list[Any], team_id: int) -> list[str]:
        """Dedupe/rebuild this engine's schema rows against discovered schemas on refresh; returns
        the extra schema names deleted during reconciliation."""
        raise NotImplementedError()

    def refresh_name_substitutions(
        self, *, source: Any, source_schemas: list[Any], team_id: int
    ) -> dict[str, str] | None:
        """Engine-specific legacy-row name remapping applied before schema sync. ``None`` means the
        engine has none, so the caller falls back to the generic multi-schema migration. Only
        Postgres overrides this (its bespoke legacy-dedup); an empty dict from Postgres still counts
        as "handled" and suppresses the generic path."""
        return None


class _PostgresEngine(DirectQueryEngine):
    engine = "postgres"
    resolves_location_in_warehouse_mode = True

    def source_table_location(self, *, schema_name, source_schema, default_schema, default_catalog=None):
        return get_postgres_source_location(
            schema_name=schema_name, schema_metadata=_location_metadata(source_schema), default_schema=default_schema
        )

    def columns_to_dwh_columns(self, source_columns):
        return postgres_columns_to_dwh_columns(source_columns)

    def upsert_table(
        self, existing_table, *, schema_name, source, columns, source_catalog, source_schema, source_table_name
    ):
        return upsert_direct_postgres_table(
            existing_table,
            schema_name=schema_name,
            source=source,
            columns=columns,
            source_catalog=source_catalog,
            source_schema=source_schema,
            source_table_name=source_table_name,
        )

    def reproject_table(self, schema_row, *, source, enabled_columns):
        return reproject_direct_postgres_table(schema_row, source=source, enabled_columns=enabled_columns)

    def hide_table(self, table):
        hide_direct_postgres_table(table)

    def reconcile_schemas(self, *, source, source_schemas, team_id):
        return reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)

    def refresh_name_substitutions(self, *, source, source_schemas, team_id):
        return reconcile_refresh_name_substitutions(source=source, source_schemas=source_schemas, team_id=team_id)


class _MySQLEngine(DirectQueryEngine):
    engine = "mysql"

    def source_table_location(self, *, schema_name, source_schema, default_schema, default_catalog=None):
        # MySQL has no catalog layer; `database` (passed as default_catalog) is the schema fallback.
        source_schema_name, source_table_name = get_mysql_source_location(
            schema_name=schema_name,
            schema_metadata=_location_metadata(source_schema),
            default_schema=default_schema or default_catalog,
        )
        return None, source_schema_name, source_table_name

    def columns_to_dwh_columns(self, source_columns):
        return mysql_columns_to_dwh_columns(source_columns)

    def upsert_table(
        self, existing_table, *, schema_name, source, columns, source_catalog, source_schema, source_table_name
    ):
        # MySQL has no catalog; `source_catalog` is ignored.
        return upsert_direct_mysql_table(
            existing_table,
            schema_name=schema_name,
            source=source,
            columns=columns,
            source_schema=source_schema,
            source_table_name=source_table_name,
        )

    def reproject_table(self, schema_row, *, source, enabled_columns):
        return reproject_direct_mysql_table(schema_row, source=source, enabled_columns=enabled_columns)

    def hide_table(self, table):
        hide_direct_mysql_table(table)

    def reconcile_schemas(self, *, source, source_schemas, team_id):
        return reconcile_mysql_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


class _SnowflakeEngine(DirectQueryEngine):
    engine = "snowflake"

    def source_table_location(self, *, schema_name, source_schema, default_schema, default_catalog=None):
        catalog = source_schema.source_catalog if source_schema and source_schema.source_catalog else default_catalog
        if source_schema and source_schema.source_schema and source_schema.source_table_name:
            return catalog, source_schema.source_schema, source_schema.source_table_name

        normalized_default_schema = (
            default_schema.strip() if isinstance(default_schema, str) and default_schema.strip() else None
        )
        if normalized_default_schema is None and "." in schema_name:
            inferred_schema, inferred_table_name = schema_name.split(".", 1)
            return catalog, inferred_schema, inferred_table_name

        return catalog, normalized_default_schema or "", schema_name

    def columns_to_dwh_columns(self, source_columns):
        return snowflake_columns_to_dwh_columns(source_columns)

    def upsert_table(
        self, existing_table, *, schema_name, source, columns, source_catalog, source_schema, source_table_name
    ):
        return upsert_direct_snowflake_table(
            existing_table,
            schema_name=schema_name,
            source=source,
            columns=columns,
            source_catalog=source_catalog,
            source_schema=source_schema,
            source_table_name=source_table_name,
        )

    def reproject_table(self, schema_row, *, source, enabled_columns):
        return reproject_direct_snowflake_table(schema_row, source=source, enabled_columns=enabled_columns)

    def hide_table(self, table):
        hide_direct_snowflake_table(table)

    def reconcile_schemas(self, *, source, source_schemas, team_id):
        return reconcile_snowflake_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


class _RedshiftEngine(DirectQueryEngine):
    engine = "redshift"

    def source_table_location(self, *, schema_name, source_schema, default_schema, default_catalog=None):
        return get_redshift_source_location(
            schema_name=schema_name,
            schema_metadata=_location_metadata(source_schema),
            default_catalog=default_catalog,
            default_schema=default_schema,
        )

    def columns_to_dwh_columns(self, source_columns):
        # Redshift information_schema types are Postgres-style, so reuse the Postgres mapper.
        return postgres_columns_to_dwh_columns(source_columns)

    def upsert_table(
        self, existing_table, *, schema_name, source, columns, source_catalog, source_schema, source_table_name
    ):
        return upsert_direct_redshift_table(
            existing_table,
            schema_name=schema_name,
            source=source,
            columns=columns,
            source_catalog=source_catalog,
            source_schema=source_schema,
            source_table_name=source_table_name,
        )

    def reproject_table(self, schema_row, *, source, enabled_columns):
        return reproject_direct_redshift_table(schema_row, source=source, enabled_columns=enabled_columns)

    def hide_table(self, table):
        hide_direct_redshift_table(table)

    def reconcile_schemas(self, *, source, source_schemas, team_id):
        return reconcile_redshift_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


_ENGINES: dict[str, DirectQueryEngine] = {
    engine.engine: engine for engine in (_PostgresEngine(), _MySQLEngine(), _SnowflakeEngine(), _RedshiftEngine())
}


def get_direct_query_engine(engine: str | None) -> DirectQueryEngine | None:
    """Adapter for a source's ``direct_engine``, or None for non-direct-capable sources."""
    if engine is None:
        return None
    return _ENGINES.get(engine)
