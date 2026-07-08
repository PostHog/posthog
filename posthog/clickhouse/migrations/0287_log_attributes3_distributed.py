from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOG_ATTRIBUTES3_DISTRIBUTED_TABLE_SQL

# Read path for log_attributes3 (0282), which carries severity_text in its sort key.
# A separate distributed table rather than repointing log_attributes_distributed:
# gen 3 only holds data since its MVs went live, so cutting the shared read table over
# before that floor ages past the TTL would drop history for existing readers. Readers
# that need severity opt in here; the shared table cuts over once gen 3 covers retention.
operations = [
    run_sql_with_exceptions(LOG_ATTRIBUTES3_DISTRIBUTED_TABLE_SQL(), node_roles=[NodeRole.LOGS]),
]
