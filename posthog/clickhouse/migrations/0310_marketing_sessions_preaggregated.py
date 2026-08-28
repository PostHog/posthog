from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.marketing_sessions_sql import (
    DISTRIBUTED_MARKETING_SESSIONS_TABLE_SQL,
    SHARDED_MARKETING_SESSIONS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_MARKETING_SESSIONS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_MARKETING_SESSIONS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Also on AUX, for ad-hoc reads directly from an AUX node.
    run_sql_with_exceptions(
        DISTRIBUTED_MARKETING_SESSIONS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
