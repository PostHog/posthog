from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The table is empty and has no readers: the writer never shipped, and the
# preview tick only reads logs_distributed. Dropping it frees the name for the
# summing rollup table that replaces the generation-based design.
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
