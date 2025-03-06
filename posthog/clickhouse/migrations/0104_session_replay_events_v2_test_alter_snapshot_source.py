from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
)

ALTER_SNAPSHOT_SOURCE_SQL = (
    lambda: """
ALTER TABLE {table_name}
    MODIFY COLUMN `snapshot_source` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC'))
""".format(
        table_name=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
    )
)

operations = [
    run_sql_with_exceptions(ALTER_SNAPSHOT_SOURCE_SQL(), sharded=True),
]
