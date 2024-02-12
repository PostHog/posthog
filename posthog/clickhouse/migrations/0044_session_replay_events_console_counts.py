from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_CONSOLE_COUNTS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_CONSOLE_COUNTS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_CONSOLE_COUNTS_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)


operations = [
    # looking at past migrations we have to drop materialized views and kafka tables first
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # alter the target tables
    run_sql_with_exceptions(ADD_CONSOLE_COUNTS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(ADD_CONSOLE_COUNTS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(ADD_CONSOLE_COUNTS_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
