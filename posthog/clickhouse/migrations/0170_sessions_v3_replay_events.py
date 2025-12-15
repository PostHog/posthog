from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.migrations_v3 import ADD_HAS_REPLAY_EVENTS, DROP_PERSON_ID
from posthog.models.raw_sessions.sessions_v3 import (
    DISTRIBUTED_RAW_SESSIONS_TABLE_V3,
    SHARDED_RAW_SESSIONS_TABLE_V3,
    WRITABLE_RAW_SESSIONS_TABLE_V3,
)

operations = [
    # this is a copy of migration 164, to apply the changes that were introduced at the same time as the migration verifier
    # drop person ID
    run_sql_with_exceptions(
        DROP_PERSON_ID.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        DROP_PERSON_ID.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DROP_PERSON_ID.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # add has_replay_events
    run_sql_with_exceptions(
        ADD_HAS_REPLAY_EVENTS.format(table_name=SHARDED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ADD_HAS_REPLAY_EVENTS.format(table_name=WRITABLE_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        ADD_HAS_REPLAY_EVENTS.format(table_name=DISTRIBUTED_RAW_SESSIONS_TABLE_V3()),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
