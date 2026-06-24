from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Inlined drop SQLs — we intentionally do not import the conversion_goal_attributed_sql module
# (kept only as a legacy stub for migration 0261) so this migration stays self-contained.
DISTRIBUTED_DROP = "DROP TABLE IF EXISTS conversion_goal_attributed_preaggregated"
SHARDED_DROP = "DROP TABLE IF EXISTS sharded_conversion_goal_attributed_preaggregated SYNC"

operations = [
    run_sql_with_exceptions(DISTRIBUTED_DROP, node_roles=[NodeRole.AUX, NodeRole.DATA]),
    run_sql_with_exceptions(SHARDED_DROP, node_roles=[NodeRole.AUX]),
]
