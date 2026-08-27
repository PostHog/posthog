from posthog.hogql.direct_sql.adapter import (
    DirectQueryPrincipal,
    DirectQueryRequest,
    DirectQueryResult,
    DirectSQLAdapter,
)
from posthog.hogql.direct_sql.capability import direct_capable_source_types, is_direct_capable
from posthog.hogql.direct_sql.clickhouse_adapter import ClickHouseAdapter
from posthog.hogql.direct_sql.duckgres_adapter import DuckgresRawAdapter
from posthog.hogql.direct_sql.motherduck_adapter import MotherDuckAdapter
from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter
from posthog.hogql.direct_sql.postgres_adapter import PostgresAdapter
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.direct_sql.redshift_adapter import RedshiftAdapter
from posthog.hogql.direct_sql.registry import get_adapter, register_adapter, registered_engines
from posthog.hogql.direct_sql.snowflake_adapter import SnowflakeAdapter
from posthog.hogql.direct_sql.trino_adapter import TrinoAdapter

from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import ManagedWarehouseSQLMode

register_adapter(PostgresAdapter())
register_adapter(MySQLAdapter())
register_adapter(SnowflakeAdapter())
register_adapter(RedshiftAdapter())
register_adapter(ClickHouseAdapter())
register_adapter(MotherDuckAdapter())
register_adapter(TrinoAdapter())


def get_raw_adapter_for_source(source: ExternalDataSource) -> DirectSQLAdapter | None:
    if source.has_managed_warehouse_prefix:
        managed_warehouse_mode = source.managed_warehouse_sql_mode
        if not source.is_managed_warehouse or not is_direct_capable(source):
            return None
        if managed_warehouse_mode == ManagedWarehouseSQLMode.BUILT_IN:
            return DuckgresRawAdapter()
        if managed_warehouse_mode == ManagedWarehouseSQLMode.UNAVAILABLE:
            return None
    return get_adapter(source.direct_engine)


__all__ = [
    "DirectQueryRequest",
    "DirectQueryPrincipal",
    "DirectQueryResult",
    "DirectSQLAdapter",
    "ClickHouseAdapter",
    "DuckgresRawAdapter",
    "MotherDuckAdapter",
    "PostgresAdapter",
    "MySQLAdapter",
    "SnowflakeAdapter",
    "TrinoAdapter",
    "RedshiftAdapter",
    "direct_capable_source_types",
    "is_direct_capable",
    "ensure_single_direct_statement",
    "get_adapter",
    "get_raw_adapter_for_source",
    "register_adapter",
    "registered_engines",
]
