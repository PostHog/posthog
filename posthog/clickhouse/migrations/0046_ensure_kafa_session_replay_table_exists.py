from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.session_replay_event.migrations_sql import (
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.models.session_replay_event.sql import (
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

operations = [
    # manual incident resolution (or the aftermath of it)
    # left the EU cluster without the kafka table
    # this command ensures that kafka table is present on any server it is not already on
    # it is a no-op in every situation after it has run once, and a no-op if the problem doesn't exist
    # e.g. on a new install
    # we have to drop materialized view first so that we're no longer pulling from kakfa
    # then we drop the kafka table
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # now we would normally alter the target tables, but here do nothing
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
