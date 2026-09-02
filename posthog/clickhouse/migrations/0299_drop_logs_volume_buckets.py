from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Safe to drop without data loss: the table is empty and nothing reads it.
# max_table_size_to_drop = 0 lifts the server's drop-size guard, which would otherwise
# refuse the drop on any node where the table turned out to hold data.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_volume_buckets_distributed SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_volume_buckets SYNC SETTINGS max_table_size_to_drop = 0",
        node_roles=[NodeRole.LOGS],
    ),
]
