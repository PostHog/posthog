from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.session_recordings.sql.session_replay_event_v2_test_migrations_sql import (
    ADD_MISSING_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL,
    ADD_MISSING_COLUMNS_SHARDED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL,
    ADD_MISSING_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL,
    DROP_SESSION_REPLAY_EVENTS_V2_TEST_MV_TABLE_SQL,
    DROP_KAFKA_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL,
)
from posthog.session_recordings.sql.session_replay_event_v2_test_sql import (
    SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_SQL,
    SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL,
)

operations = [
    # First, drop the materialized view so it's no longer pulling from Kafka
    run_sql_with_exceptions(DROP_SESSION_REPLAY_EVENTS_V2_TEST_MV_TABLE_SQL()),
    # Then drop the Kafka table
    run_sql_with_exceptions(DROP_KAFKA_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL()),
    # Now we can alter the target tables in the correct order:
    # 1. Sharded table (physical storage)
    run_sql_with_exceptions(ADD_MISSING_COLUMNS_SHARDED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL()),
    # 2. Writable table (for writing to sharded table)
    run_sql_with_exceptions(ADD_MISSING_COLUMNS_WRITABLE_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL()),
    # 3. Distributed table (for reading)
    run_sql_with_exceptions(ADD_MISSING_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL()),
    # Also run on coordinator node without the cluster clause
    run_sql_with_exceptions(
        ADD_MISSING_COLUMNS_DISTRIBUTED_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(on_cluster=False),
        node_role=NodeRole.COORDINATOR,
    ),
    # Finally, recreate the Kafka table and materialized view with the updated schema
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_SQL()),
    run_sql_with_exceptions(SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL()),
]
