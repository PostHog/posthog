from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL
from posthog.session_recordings.sql.session_replay_event_sql import SESSION_REPLAY_EVENTS_TABLE_MV_SQL

operations = [
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
