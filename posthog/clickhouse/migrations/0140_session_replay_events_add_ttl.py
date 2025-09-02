from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    SET_TTL_ONLY_DROP_PARTS_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)

operations = [
    # looking at past migrations we have to drop materialized views and kafka tables first
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False)),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False)),
    # alter the target tables
    run_sql_with_exceptions(SET_TTL_ONLY_DROP_PARTS_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    run_sql_with_exceptions(ADD_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False)),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False)),
]
