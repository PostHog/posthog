from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
)

# Converges `experiment_metric_events_preaggregated` to its intended layout:
# sharded backing on AUX, query-side Distributed wrapper on AUX + DATA.
# The underlying SQL uses `CREATE TABLE IF NOT EXISTS`, so this is a no-op
# on any node that already has the table.

operations = [
    run_sql_with_exceptions(
        SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
