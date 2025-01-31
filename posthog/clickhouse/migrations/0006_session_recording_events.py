from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_recording_event_sql import (
    DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL,
    KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL,
    ON_CLUSTER_CLAUSE,
    SESSION_RECORDING_EVENTS_TABLE_MV_SQL,
    SESSION_RECORDING_EVENTS_TABLE_SQL,
    WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL,
)

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL = (
    lambda on_cluster=True: """
    ALTER TABLE session_recording_events
    {on_cluster_clause}
    COMMENT COLUMN has_full_snapshot 'column_materializer::has_full_snapshot'
""".format(on_cluster_clause=ON_CLUSTER_CLAUSE() if on_cluster else "")
)

operations = [
    run_sql_with_exceptions(WRITABLE_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL()),
    run_sql_with_exceptions(KAFKA_SESSION_RECORDING_EVENTS_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_RECORDING_EVENTS_TABLE_MV_SQL()),
    run_sql_with_exceptions(
        DISTRIBUTED_SESSION_RECORDING_EVENTS_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR
    ),
    run_sql_with_exceptions(
        SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL(on_cluster=False),
        node_role=NodeRole.COORDINATOR,
    ),
]
