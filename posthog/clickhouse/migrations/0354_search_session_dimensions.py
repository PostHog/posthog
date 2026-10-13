from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE sharded_web_sessions_dimensional_preaggregated ADD COLUMN IF NOT EXISTS entry_url String, ADD COLUMN IF NOT EXISTS has_gclid UInt8, ADD COLUMN IF NOT EXISTS has_msclkid UInt8, ADD COLUMN IF NOT EXISTS session_max_inserted_at DateTime64(6, 'UTC')",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        "ALTER TABLE web_sessions_dimensional_preaggregated ADD COLUMN IF NOT EXISTS entry_url String, ADD COLUMN IF NOT EXISTS has_gclid UInt8, ADD COLUMN IF NOT EXISTS has_msclkid UInt8, ADD COLUMN IF NOT EXISTS session_max_inserted_at DateTime64(6, 'UTC')",
        node_roles=[NodeRole.DATA, NodeRole.AUX],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
