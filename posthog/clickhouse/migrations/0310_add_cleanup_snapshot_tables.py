from posthog.clickhouse.cleanup_snapshots import CLEANUP_SNAPSHOT_TABLE_SQL
from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(table_sql(), node_roles=[NodeRole.DATA]) for table_sql in CLEANUP_SNAPSHOT_TABLE_SQL
]
