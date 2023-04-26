from django.conf import settings

from posthog.clickhouse.indexes import index_by_kafka_timestamp
from posthog.clickhouse.kafka_engine import KAFKA_COLUMNS, kafka_engine, ttl_period
from posthog.clickhouse.table_engines import Distributed, ReplicationScheme, AggregatingMergeTree
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS

SESSION_REPLAY_EVENTS_DATA_TABLE = lambda: "sharded_session_replay_events"

SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
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
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, session_id, toStartOfHour(timestamp))
SETTINGS index_granularity=512
"""
).format(
    table_name=SESSION_REPLAY_EVENTS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    extra_fields=f"""
    {KAFKA_COLUMNS}
    , {index_by_kafka_timestamp(SESSION_REPLAY_EVENTS_DATA_TABLE())}
    """,
    engine=SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE(),
    ttl_period=ttl_period(),
)

KAFKA_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS),
    extra_fields="",
)

SESSION_REPLAY_EVENTS_TABLE_MV_SQL = lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_mv ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
session_id,
team_id,
any(distinct_id),
max(timestamp),
minState(timestamp) AS first_timestamp,
maxState(timestamp) AS last_timestamp,
any(first_url),
sumState(click_count),
sumState(keypress_count),
sumState(mouse_activity_count)
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
    extra_fields=KAFKA_COLUMNS,
    materialized_columns="",
)

# This table is responsible for reading from session_replay_events on a cluster setting
DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(), sharding_key="sipHash64(distinct_id)"),
    extra_fields=KAFKA_COLUMNS,
)


DROP_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)
