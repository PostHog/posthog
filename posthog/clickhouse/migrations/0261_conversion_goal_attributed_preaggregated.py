from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.conversion_goal_attributed_sql import (
    DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL,
    SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_CONVERSION_GOAL_ATTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
