from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE

"""
These tables were used in testing the migration to session replay v2 ingestion
A skeleton is kept around to maintain migration history
but it isn't used for anything
"""

# first we would drop the materialized view so we're not pulling from the kafka table
# then the kafka table
# then the rest - the order doesn't _really_ matter since we're not querying this data anywhere
SESSION_REPLAY_EVENTS_V2_TEST_TABLES = [
    "session_replay_events_v2_test_mv",
    "kafka_session_replay_events_v2_test",
    "session_replay_events_v2_test",
    "writable_session_replay_events_v2_test",
    "sharded_session_replay_events_v2_test",
]


def DROP_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL(table: str):
    return f"DROP TABLE IF EXISTS {table} {ON_CLUSTER_CLAUSE(False)}"
