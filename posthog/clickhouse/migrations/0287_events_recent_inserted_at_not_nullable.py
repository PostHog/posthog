from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE distributed_events_recent MODIFY COLUMN IF EXISTS inserted_at DateTime64(6, 'UTC') DEFAULT now64()",
        node_roles=[NodeRole.DATA],
    ),
]
