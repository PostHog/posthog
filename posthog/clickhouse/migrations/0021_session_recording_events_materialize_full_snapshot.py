from infi.clickhouse_orm import migrations

from posthog.clickhouse.client import sync_execute

SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL = (
    lambda: """
    ALTER TABLE session_recording_events
    COMMENT COLUMN has_full_snapshot 'column_materializer::has_full_snapshot'
""".format()
)


def create_has_full_snapshot_materialized_column(database):
    sync_execute(
        f"""
        ALTER TABLE sharded_session_recording_events
        ADD COLUMN IF NOT EXISTS
        has_full_snapshot Int8 MATERIALIZED JSONExtractBool(snapshot_data, 'has_full_snapshot')
    """
    )
    sync_execute(
        f"""
        ALTER TABLE session_recording_events
        ADD COLUMN IF NOT EXISTS
        has_full_snapshot Int8
    """
    )

    sync_execute(SESSION_RECORDING_EVENTS_MATERIALIZED_COLUMN_COMMENTS_SQL())


operations = [migrations.RunPython(create_has_full_snapshot_materialized_column)]
