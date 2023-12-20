from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ALTER_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

operations = [
    # We're having issues with the table as it is with `LowCardinality` type
    # Let's remove that by modifying the column
    run_sql_with_exceptions(ALTER_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
]
