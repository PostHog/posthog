from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, DirectSQLAdapter
from posthog.hogql.direct_sql.capability import direct_capable_source_types, is_direct_capable
from posthog.hogql.direct_sql.clickhouse_adapter import ClickHouseAdapter
from posthog.hogql.direct_sql.motherduck_adapter import MotherDuckAdapter
from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter
from posthog.hogql.direct_sql.postgres_adapter import PostgresAdapter
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.direct_sql.redshift_adapter import RedshiftAdapter
from posthog.hogql.direct_sql.registry import get_adapter, register_adapter, registered_engines
from posthog.hogql.direct_sql.snowflake_adapter import SnowflakeAdapter

register_adapter(PostgresAdapter())
register_adapter(MySQLAdapter())
register_adapter(SnowflakeAdapter())
register_adapter(RedshiftAdapter())
register_adapter(ClickHouseAdapter())
register_adapter(MotherDuckAdapter())

__all__ = [
    "DirectQueryRequest",
    "DirectQueryResult",
    "DirectSQLAdapter",
    "ClickHouseAdapter",
    "MotherDuckAdapter",
    "PostgresAdapter",
    "MySQLAdapter",
    "SnowflakeAdapter",
    "RedshiftAdapter",
    "direct_capable_source_types",
    "is_direct_capable",
    "ensure_single_direct_statement",
    "get_adapter",
    "register_adapter",
    "registered_engines",
]
