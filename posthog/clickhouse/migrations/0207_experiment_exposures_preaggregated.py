from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.experiment_exposures_sql import (
    DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE_SQL,
    SHARDED_EXPERIMENT_EXPOSURES_TABLE_SQL,
)

operations = [
    # Create sharded table on data nodes
    run_sql_with_exceptions(
        SHARDED_EXPERIMENT_EXPOSURES_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Create distributed table on data + coordinator nodes
    run_sql_with_exceptions(
        DISTRIBUTED_EXPERIMENT_EXPOSURES_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
