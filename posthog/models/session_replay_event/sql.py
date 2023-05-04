from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, AggregatingMergeTree
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS

SESSION_REPLAY_EVENTS_DATA_TABLE = lambda: "sharded_session_replay_events"

"""Kafka needs slightly different column setup. It receives individual events, not aggregates."""
KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),
    first_url Nullable(VARCHAR),
    click_count Int64,
    keypress_count Int64,
    mouse_activity_count Int64,
    active_milliseconds Int64
) ENGINE = {engine}
"""

SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    first_url Nullable(VARCHAR),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64)
) ENGINE = {engine}
"""


SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "session_replay_events", replication_scheme=ReplicationScheme.SHARDED
)

SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    SESSION_REPLAY_EVENTS_TABLE_BASE_SQL
    + """
    PARTITION BY toYYYYMM(first_timestamp)
    ORDER BY (team_id, toDate(first_timestamp), session_id, first_timestamp)
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE(),
)

KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: KAFKA_SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
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
min(first_timestamp) AS first_timestamp,
max(last_timestamp) AS last_timestamp,
any(first_url) AS first_url,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count,
sum(active_milliseconds) as active_milliseconds
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
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
)

# This table is responsible for reading from session_replay_events on a cluster setting
DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
)


DROP_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

SELECT_SUMMARIZED_SESSIONS = """
select
   session_id,
   any(team_id),
   any(distinct_id),
   min(first_timestamp),
   max(last_timestamp),
   dateDiff('SECOND', min(first_timestamp), max(last_timestamp)) as duration,
   sum(click_count),
   sum(keypress_count),
   sum(mouse_activity_count),
   round((sum(active_milliseconds)/1000)/duration, 2) as active_time
from session_replay_events
prewhere team_id = %(team_id)s
and first_timestamp >= %(start_time)s
and last_timestamp <= %(end_time)s
and session_id in (%(session_ids)s)
group by session_id
"""
