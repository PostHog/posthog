from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, AggregatingMergeTree
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS

SESSION_REPLAY_EVENTS_DATA_TABLE = lambda: "sharded_session_replay_events"

"""
These base tables have an optional timestamp column

When writing a single event to kafka for ingestion timestamp is provided
Those events are ingested in a batch and each batch
has interim min and max aggregates for timestamp.

This lets the aggregating table only store min and max timestamp
instead of e.g. an array of timestamps
"""
SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    {optionalTimestampColumn}
    first_timestamp AggregateFunction(min, DateTime64(6, 'UTC')),
    last_timestamp AggregateFunction(max, DateTime64(6, 'UTC')),
    first_url Nullable(VARCHAR),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64)
) ENGINE = {engine}
"""


SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "session_replay_events", replication_scheme=ReplicationScheme.SHARDED
)

SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    SESSION_REPLAY_EVENTS_TABLE_BASE_SQL
    + """ORDER BY (team_id, session_id)
SETTINGS index_granularity=512
"""
).format(
    optionalTimestampColumn="",
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE(),
)

KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    optionalTimestampColumn="timestamp DateTime64(6, 'UTC'),",
    table_name="kafka_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS),
)

SESSION_REPLAY_EVENTS_TABLE_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
session_id,
team_id,
any(distinct_id) as distinct_id,
minState(timestamp) AS first_timestamp,
maxState(timestamp) AS last_timestamp,
any(first_url) AS first_url,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count
FROM {database}.kafka_session_replay_events
group by session_id, team_id
""".format(
    target_table="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    database=settings.CLICKHOUSE_DATABASE,
)


# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_session_replay_events based on a sharding key.
WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    optionalTimestampColumn="",
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
)

# This table is responsible for reading from session_replay_events on a cluster setting
DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    optionalTimestampColumn="",
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
)


DROP_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

SELECT_ALL_SUMMARIZED_SESSIONS = """
select
   session_id,
   any(team_id),
   any(distinct_id),
   minMerge(first_timestamp),
   maxMerge(last_timestamp),
   sum(click_count),
   sum(keypress_count),
   sum(mouse_activity_count)
from session_replay_events
group by session_id
"""
