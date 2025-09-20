from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_migrations_sql import (
    ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
    REMOVE_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_TABLE_MV_SQL,
)

operations = [
    # looking at past migrations we have to drop materialized views and kafka tables first
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
    # alter the target tables
    run_sql_with_exceptions(
        REMOVE_TTL_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(DROP_RETENTION_PERIOD_DAYS_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(
        DROP_RETENTION_PERIOD_DAYS_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(DROP_RETENTION_PERIOD_DAYS_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    run_sql_with_exceptions(ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(
        ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(ADD_RETENTION_PERIOD_DAYS_AGGREGATE_TYPE_SESSION_REPLAY_EVENTS_TABLE_SQL(), sharded=True),
    # and then recreate the materialized views and kafka tables
    run_sql_with_exceptions(KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_TABLE_MV_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
]
