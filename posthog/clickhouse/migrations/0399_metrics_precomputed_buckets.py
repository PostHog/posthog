from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics.precomputed_buckets import METRICS_PRECOMPUTED_BUCKETS_TABLE_SQL
from posthog.run_mode import run_mode

# The table sits next to metrics4_samples, which the fill reads. In cloud that is the metrics cluster. The local
# stacks run every role on one node and keep the metrics4 tables on the logs role.
operations = [
    run_sql_with_exceptions(
        METRICS_PRECOMPUTED_BUCKETS_TABLE_SQL(),
        node_roles=[NodeRole.METRICS] if run_mode().is_deployed_cloud else [NodeRole.LOGS],
    ),
]
