from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# NB the mv then kafka tables are first in this list on purpose
operations = [
    run_sql_with_exceptions("DROP TABLE IF EXISTS session_replay_events_v2_test_mv"),
    run_sql_with_exceptions("DROP TABLE IF EXISTS kafka_session_replay_events_v2_test"),
    run_sql_with_exceptions("DROP TABLE IF EXISTS session_replay_events_v2_test"),
    run_sql_with_exceptions("DROP TABLE IF EXISTS writable_session_replay_events_v2_test"),
    run_sql_with_exceptions("DROP TABLE IF EXISTS sharded_session_replay_events_v2_test"),
]
