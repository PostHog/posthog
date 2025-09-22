from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.materialized_columns import (
    ADD_COLUMN_AI_TRACE_ID_EVENTS_SQL,
    ADD_COLUMN_AI_TRACE_ID_TO_SHARDED_EVENTS_SQL,
    ADD_INDEX_AI_TRACE_ID_SHARDED_EVENTS_SQL,
)

operations = [
    run_sql_with_exceptions(ADD_COLUMN_AI_TRACE_ID_TO_SHARDED_EVENTS_SQL, node_roles=[NodeRole.DATA], sharded=True),
    run_sql_with_exceptions(ADD_COLUMN_AI_TRACE_ID_EVENTS_SQL, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(ADD_INDEX_AI_TRACE_ID_SHARDED_EVENTS_SQL, node_roles=[NodeRole.DATA], sharded=True),
]
