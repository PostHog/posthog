"""
Session Replay Events Data Flow:

┌─────────────────────────────────────────────────┐ Raw events from plugin-server
│   Kafka Topic                                   │ Contains individual events with:
│   session_replay_events_v2_test                 │ - session_id, team_id, distinct_id
└──────────────────────────┬──────────────────────┘ - first_timestamp, last_timestamp
                           │                        - block_url
                           ▼
┌─────────────────────────────────────────────────┐ Kafka Engine Table
│   kafka_session_replay_events_v2_test           │ Direct mirror of Kafka topic
│                                                 │ Same schema as Kafka messages
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐ Materialized View aggregates events:
│   session_replay_events_v2_test_mv              │ - Groups by session_id, team_id
└──────────────────────────┬──────────────────────┘ - min(first_timestamp)
                           │                        - max(last_timestamp)
                           │                        - groupUniqArrayArray(block_url)
                           ▼
┌─────────────────────────────────────────────────┐ Distributed Table
│   writable_session_replay_events_v2_test        │ Handles writing to sharded table
│                                                 │ Sharded by sipHash64(distinct_id)
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐ Physical Table (Replicated)
│   sharded_session_replay_events_v2_test         │ Stores the actual data
│                                                 │ AggregatingMergeTree engine
└──────────────────────────┬──────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────┐ Distributed Table
│   session_replay_events_v2_test                 │ Used for reading/querying data
└─────────────────────────────────────────────────┘
"""

from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    AggregatingMergeTree,
)
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST


SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE = "sharded_session_replay_events_v2_test"
SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE_ENGINE = AggregatingMergeTree(
    "session_replay_events_v2_test", replication_scheme=ReplicationScheme.SHARDED
)


"""
This table is a ClickHouse copy of the events from the Kafka topic.

We first ingest unaggregated events from Kafka, which are then processed by the materialized view
into aggregated session data. For this reason, this table needs a different column setup than
the other tables - it stores individual events with first_timestamp and last_timestamp, which
are later aggregated into min_first_timestamp and max_last_timestamp in the main table.
"""
SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_BASE_SQL = """
    CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
    (
        session_id VARCHAR,
        team_id Int64,
        distinct_id VARCHAR,
        first_timestamp DateTime64(6, 'UTC'),
        last_timestamp DateTime64(6, 'UTC'),
        block_url String,
    ) ENGINE = {engine}
"""


"""
Base schema for tables storing aggregated session replay data. Used by:
- writable_session_replay_events_v2_test: Distributed table for writing
- sharded_session_replay_events_v2_test: Physical storage with AggregatingMergeTree engine
- session_replay_events_v2_test: Distributed table for reading

The materialized view (session_replay_events_v2_test_mv) aggregates raw events into this schema,
so any column changes here must be reflected in the materialized view's SELECT statement below.
"""
SESSION_REPLAY_EVENTS_V2_TEST_TABLE_BASE_SQL = """
    CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause}
    (
        session_id VARCHAR,
        team_id Int64,
        distinct_id VARCHAR,
        min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
        max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
        block_first_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        block_last_timestamps SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        block_urls SimpleAggregateFunction(groupArrayArray, Array(String)),
    ) ENGINE = {engine}
"""


"""
Base SQL for the materialized view that transforms raw events into aggregated data.

Note: Column types must be explicitly specified in the TO clause because ClickHouse
incorrectly expands some column types during materialized view creation (specifically
LowCardinality(Nullable(String)) gets expanded to just Nullable(String)).
"""
SESSION_REPLAY_EVENTS_V2_TEST_MV_BASE_SQL = """
    CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_v2_test_mv {on_cluster_clause}
    TO {database}.writable_session_replay_events_v2_test (
        `session_id` String,
        `team_id` Int64,
        `distinct_id` String,
        `min_first_timestamp` DateTime64(6, 'UTC'),
        `max_last_timestamp` DateTime64(6, 'UTC'),
        `block_first_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        `block_last_timestamps` SimpleAggregateFunction(groupArrayArray, Array(DateTime64(6, 'UTC'))),
        `block_urls` SimpleAggregateFunction(groupArrayArray, Array(String)),
        `_timestamp` Nullable(DateTime)
    )
    AS SELECT
        session_id,
        team_id,
        distinct_id,
        min(first_timestamp) AS min_first_timestamp,
        max(last_timestamp) AS max_last_timestamp,
        groupArray(first_timestamp) AS block_first_timestamps,
        groupArray(last_timestamp) AS block_last_timestamps,
        groupArray(block_url) AS block_urls,
        max(_timestamp) as _timestamp
    FROM {database}.kafka_session_replay_events_v2_test
    GROUP BY session_id, team_id, distinct_id
"""


def SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_SQL(on_cluster=True):
    return SESSION_REPLAY_EVENTS_V2_TEST_KAFKA_TABLE_BASE_SQL.format(
        table_name="kafka_session_replay_events_v2_test",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=kafka_engine(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS_V2_TEST),
    )


def SESSION_REPLAY_EVENTS_V2_TEST_MV_SQL(on_cluster=True):
    return SESSION_REPLAY_EVENTS_V2_TEST_MV_BASE_SQL.format(
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        database=settings.CLICKHOUSE_DATABASE,
    )


def SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE_SQL(on_cluster=True):
    # Order by is used by the aggregating merge tree engine to identify candidates to merge
    # e.g. toDate(min_first_timestamp) would mean we would have one row per day per session_id
    # if CH could completely merge to match the order by.
    # It is also used to organise data to make queries faster.
    # We want the fewest rows possible but also the fastest queries.
    # Since we query by date and not by time, and order by must be in order of increasing cardinality,
    # we order by date first, then team_id, then session_id.
    # Hopefully, this is a good balance between the two.
    return (
        SESSION_REPLAY_EVENTS_V2_TEST_TABLE_BASE_SQL
        + """
            PARTITION BY toYYYYMM(min_first_timestamp)
            ORDER BY (toDate(min_first_timestamp), team_id, session_id)
            SETTINGS index_granularity=512
        """
    ).format(
        table_name=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE_ENGINE,
    )


def SESSION_REPLAY_EVENTS_V2_TEST_WRITABLE_TABLE_SQL(on_cluster=True):
    return SESSION_REPLAY_EVENTS_V2_TEST_TABLE_BASE_SQL.format(
        table_name="writable_session_replay_events_v2_test",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def SESSION_REPLAY_EVENTS_V2_TEST_DISTRIBUTED_TABLE_SQL(on_cluster=True):
    return SESSION_REPLAY_EVENTS_V2_TEST_TABLE_BASE_SQL.format(
        table_name="session_replay_events_v2_test",
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=Distributed(
            data_table=SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE,
            sharding_key="sipHash64(distinct_id)",
        ),
    )


def DROP_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE} {ON_CLUSTER_CLAUSE()}"


def TRUNCATE_SESSION_REPLAY_EVENTS_V2_TEST_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_EVENTS_V2_TEST_DATA_TABLE} {ON_CLUSTER_CLAUSE()}"
