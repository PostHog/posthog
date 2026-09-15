from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL
from posthog.session_recordings.sql.session_replay_event_sql import SESSION_REPLAY_EVENTS_TABLE_MV_SQL

operations = [
    # we have to drop materialized view because 0050 created it incorrectly
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    # now we can recreate it with explicit column definitions
    # that correctly identifies snapshot source as LowCardinality(Nullable(String))
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
