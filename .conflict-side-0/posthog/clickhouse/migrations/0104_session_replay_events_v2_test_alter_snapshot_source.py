from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_v2_test_migrations_sql import (
    REMOVE_SNAPSHOT_SOURCE_LOW_CARDINALITY_SQL,
)

operations = [
    run_sql_with_exceptions(REMOVE_SNAPSHOT_SOURCE_LOW_CARDINALITY_SQL(on_cluster=True)),
]
