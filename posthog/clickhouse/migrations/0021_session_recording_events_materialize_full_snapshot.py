from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_recording_event_sql import ON_CLUSTER_CLAUSE
from posthog.settings import CLICKHOUSE_CLUSTER

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL = (
    lambda on_cluster=True: """
    ALTER TABLE session_recording_events
    {on_cluster_clause}
    COMMENT COLUMN has_full_snapshot 'column_materializer::has_full_snapshot'
""".format(on_cluster_clause=ON_CLUSTER_CLAUSE() if on_cluster else "")
)


operations = [
    run_sql_with_exceptions(
        f"""
        ALTER TABLE sharded_session_recording_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        ADD COLUMN IF NOT EXISTS
        has_full_snapshot Int8 MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
    """
    ),
    run_sql_with_exceptions(
        f"""
        ALTER TABLE session_recording_events
        ON CLUSTER '{CLICKHOUSE_CLUSTER}'
        ADD COLUMN IF NOT EXISTS
        has_full_snapshot Int8
    """
    ),
    run_sql_with_exceptions(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL()),
    run_sql_with_exceptions(
        SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR
    ),
]
