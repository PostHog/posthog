from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.sql import (
    DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE_SQL,
    SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL,
)

operations = [
    # Create the sharded data table on DATA nodes
    run_sql_with_exceptions(
        SHARDED_PREAGGREGATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Create the readable distributed table on DATA and COORDINATOR nodes
    run_sql_with_exceptions(
        DISTRIBUTED_PREAGGREGATION_RESULTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
