from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE sharded_ai_events ADD COLUMN IF NOT EXISTS gate_drift_sanity_check UInt8 DEFAULT 0",
        node_roles=[NodeRole.AI_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
]
