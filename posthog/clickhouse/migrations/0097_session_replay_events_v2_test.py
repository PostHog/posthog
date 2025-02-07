from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_WRITABLE_TABLE_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_DISTRIBUTED_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_WRITABLE_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_DISTRIBUTED_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL()),
    run_sql_with_exceptions(
        SESSION_REPLAY_EVENTS_V2_TEST_DISTRIBUTED_TABLE_SQL(on_cluster=False), node_role=NodeRole.COORDINATOR
    ),
]
