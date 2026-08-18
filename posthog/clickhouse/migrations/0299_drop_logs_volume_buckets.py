from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# Safe to drop without data loss: the table is empty and nothing reads it.
operations = [
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_volume_buckets_distributed",
        node_roles=[NodeRole.LOGS],
    ),
    run_sql_with_exceptions(
        f"DROP TABLE IF EXISTS {DB}.logs_volume_buckets SYNC",
        node_roles=[NodeRole.LOGS],
    ),
]
