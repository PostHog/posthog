from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_BLOCK_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_BLOCK_COLUMNS_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_BLOCK_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

# The Kafka table only has block_url String (not arrays). Block array columns are only in the aggregate tables.
operations = [
    # 1. Drop the old materialized view so it's no longer pulling from Kafka
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    # 2. Drop the Kafka table
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # 3. Sharded table (physical storage)
    run_sql_with_exceptions(ADD_BLOCK_COLUMNS_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    # 4. Writable table (for writing to sharded table)
    run_sql_with_exceptions(ADD_BLOCK_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # 5. Distributed table (for reading)
    run_sql_with_exceptions(
        ADD_BLOCK_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_role=NodeRole.ALL,
    ),
    # 6. Recreate the Kafka table with the updated schema
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # 7. Recreate the materialized view with the updated schema
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
