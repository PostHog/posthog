from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "SYSTEM FLUSH LOGS",
        node_roles=[NodeRole.AI_EVENTS, NodeRole.AUX, NodeRole.OPS, NodeRole.SESSIONS],
    ),
]
