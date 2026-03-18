from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    # Drop the "ai_large" property group column and indexes from sharded_events
    run_sql_with_exceptions(
        "ALTER TABLE sharded_events DROP INDEX IF EXISTS properties_group_ai_large_keys_bf, DROP INDEX IF EXISTS properties_group_ai_large_values_bf, DROP COLUMN IF EXISTS properties_group_ai_large",
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Drop the "ai_large" property group column from events
    run_sql_with_exceptions(
        "ALTER TABLE events DROP COLUMN IF EXISTS properties_group_ai_large",
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
