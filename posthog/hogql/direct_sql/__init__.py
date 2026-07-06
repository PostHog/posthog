from posthog.hogql.direct_sql.adapter import DirectQueryRequest, DirectQueryResult, DirectSQLAdapter
from posthog.hogql.direct_sql.capability import direct_capable_source_types, is_direct_capable
from posthog.hogql.direct_sql.mysql_adapter import MySQLAdapter
from posthog.hogql.direct_sql.postgres_adapter import PostgresAdapter
from posthog.hogql.direct_sql.raw_sql import ensure_single_direct_statement
from posthog.hogql.direct_sql.registry import get_adapter, register_adapter, registered_engines
from posthog.hogql.direct_sql.snowflake_adapter import SnowflakeAdapter

register_adapter(PostgresAdapter())
register_adapter(MySQLAdapter())
register_adapter(SnowflakeAdapter())

__all__ = [
    "DirectQueryRequest",
    "DirectQueryResult",
    "DirectSQLAdapter",
    "PostgresAdapter",
    "MySQLAdapter",
    "SnowflakeAdapter",
    "direct_capable_source_types",
    "is_direct_capable",
    "ensure_single_direct_statement",
    "get_adapter",
    "register_adapter",
    "registered_engines",
]
