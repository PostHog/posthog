from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_COLUMN_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_DISTRIBUTED_TABLE_SQL,
    DROP_WRITABLE_SESSION_REPLAY_TABLE_SQL,
)

""" We need to touch each of these
┌─name───────────────────────────┐
│ kafka_session_replay_events    │
│ session_replay_events          │
│ session_replay_events_mv       │
│ sharded_session_replay_events  │
│ writable_session_replay_events │
└────────────────────────────────┘
"""

operations = [
    # we have to drop the snapshot_sources column because of an issue with `LowCardinality`
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DROP_SESSION_REPLAY_DISTRIBUTED_TABLE_SQL()),
    run_sql_with_exceptions(DROP_WRITABLE_SESSION_REPLAY_TABLE_SQL()),
    run_sql_with_exceptions(DROP_COLUMN_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # now we can recreate it without the `LowCardinality` type
    run_sql_with_exceptions(ADD_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
