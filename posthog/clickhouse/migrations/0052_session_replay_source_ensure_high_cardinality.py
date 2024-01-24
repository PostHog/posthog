from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SOURCE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SOURCE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_HIGH_CARDINALITY_SOURCE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_HIGH_CARDINALITY_SOURCE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_HIGH_CARDINALITY_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
)

operations = [
    # we have to drop materialized view first so that we're no longer pulling from kakfa
    # then we drop the kafka table
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # now we can drop the snapshot source column, it's currently unused so safe to drop,
    # and in some deployments might still have low cardinality as part of the type
    # this should be fine but CH really doesn't like it
    run_sql_with_exceptions(DROP_SOURCE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DROP_SOURCE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DROP_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # now we can add the snapshot source columns back without the low cardinality
    run_sql_with_exceptions(ADD_HIGH_CARDINALITY_SOURCE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(ADD_HIGH_CARDINALITY_SOURCE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(ADD_HIGH_CARDINALITY_SOURCE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL()),
]
