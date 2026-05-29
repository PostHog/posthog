from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Inlined drop SQLs — the conversion_goal_attributed_sql module is removed in this migration's PR;
# we intentionally do not import it so this migration keeps working from history.
DISTRIBUTED_DROP = "DROP TABLE IF EXISTS conversion_goal_attributed_preaggregated"
SHARDED_DROP = "DROP TABLE IF EXISTS sharded_conversion_goal_attributed_preaggregated SYNC"

operations = [
    run_sql_with_exceptions(DISTRIBUTED_DROP, node_roles=[NodeRole.AUX, NodeRole.DATA]),
    run_sql_with_exceptions(SHARDED_DROP, node_roles=[NodeRole.AUX]),
]
