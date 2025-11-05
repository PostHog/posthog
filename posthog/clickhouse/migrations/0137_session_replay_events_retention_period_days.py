from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
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
    run_sql_with_exceptions(ADD_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(
        ADD_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(ADD_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    run_sql_with_exceptions(DROP_RETENTION_PERIOD_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(
        DROP_RETENTION_PERIOD_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(DROP_RETENTION_PERIOD_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False)),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False)),
]
