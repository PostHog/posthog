from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, DirectSQLAdapter
from posthog.hogql.direct_sql.capability import direct_capable_source_types, is_direct_capable
from posthog.hogql.direct_sql.clickhouse_adapter import ClickHouseAdapter
from posthog.hogql.direct_sql.duckgres_adapter import DuckgresRawAdapter
from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter
from posthog.hogql.direct_sql.postgres_adapter import PostgresAdapter
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.direct_sql.redshift_adapter import RedshiftAdapter
from posthog.hogql.direct_sql.registry import get_adapter, register_adapter, registered_engines
from posthog.hogql.direct_sql.snowflake_adapter import SnowflakeAdapter

from products.warehouse_sources.backend.facade.models import MANAGED_WAREHOUSE_SOURCE_PREFIX, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

register_adapter(PostgresAdapter())
register_adapter(MySQLAdapter())
register_adapter(SnowflakeAdapter())
register_adapter(RedshiftAdapter())
register_adapter(ClickHouseAdapter())


def get_raw_adapter_for_source(source: ExternalDataSource) -> DirectSQLAdapter | None:
    metadata = source.connection_metadata
    if (
        source.is_system_managed
        and source.prefix == MANAGED_WAREHOUSE_SOURCE_PREFIX
        and isinstance(metadata, dict)
        and metadata.get("engine") == "duckdb"
        and source.source_type == ExternalDataSourceType.POSTGRES
        and is_direct_capable(source)
    ):
        return DuckgresRawAdapter()
    return get_adapter(source.direct_engine)


__all__ = [
    "DirectQueryRequest",
    "DirectQueryResult",
    "DirectSQLAdapter",
    "ClickHouseAdapter",
    "DuckgresRawAdapter",
    "PostgresAdapter",
    "MySQLAdapter",
    "SnowflakeAdapter",
    "RedshiftAdapter",
    "direct_capable_source_types",
    "is_direct_capable",
    "ensure_single_direct_statement",
    "get_adapter",
    "get_raw_adapter_for_source",
    "register_adapter",
    "registered_engines",
]
