from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_VIEW_SQL
from posthog.run_mode import run_mode

# The view now leaves out Prometheus stale markers. CREATE OR REPLACE VIEW changes no data.
# In cloud the view lives only on the metrics cluster, since 0379 dropped it from the logs cluster.
# The local stacks run every role on one node and still keep it on the logs role.
operations = [
    run_sql_with_exceptions(
        METRICS4_VIEW_SQL(),
        node_roles=[NodeRole.METRICS] if run_mode().is_deployed_cloud else [NodeRole.LOGS],
    ),
]
