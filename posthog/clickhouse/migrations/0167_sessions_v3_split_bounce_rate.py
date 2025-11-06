from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import SPLIT_BOUNCE_RATE
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)

operations = [
    run_sql_with_exceptions(
        SPLIT_BOUNCE_RATE.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        SPLIT_BOUNCE_RATE.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()), node_roles=[NodeRole.DATA]
    ),
    run_sql_with_exceptions(
        SPLIT_BOUNCE_RATE.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
