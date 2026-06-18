from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_metric_events_sql import (
    DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
    SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL,
)

operations = [
    # Create sharded table on aux cluster
    run_sql_with_exceptions(
        SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # Create distributed table on aux cluster + data nodes (for querying)
    run_sql_with_exceptions(
        DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
