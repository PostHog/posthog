from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_sql import (
    DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    SESSION_REPLAY_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
