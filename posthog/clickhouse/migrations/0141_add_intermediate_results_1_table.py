from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.intermediate_results.sql import (
    DISTRIBUTED_INTERMEDIATE_RESULTS_SQL,
    SHARDED_INTERMEDIATE_RESULTS_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_INTERMEDIATE_RESULTS_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_INTERMEDIATE_RESULTS_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
