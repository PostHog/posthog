from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
)

ALTER_SNAPSHOT_SOURCE_SQL = f"""
ALTER TABLE {SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE}
    MODIFY COLUMN `snapshot_source` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
"""

operations = [
    run_sql_with_exceptions(ALTER_SNAPSHOT_SOURCE_SQL(), sharded=True),
]
