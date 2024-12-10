from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    AggregatingMergeTree,
)
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS

SESSION_REPLAY_EVENTS_DATA_TABLE = lambda: "sharded_session_replay_events"

"""
Kafka needs slightly different column setup. It receives individual events, not aggregates.
We write first_timestamp and last_timestamp as individual records
They will be grouped as min_first_timestamp and max_last_timestamp in the main table
"""
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
    active_milliseconds Int64,
    console_log_count Int64,
    console_warn_count Int64,
    console_error_count Int64,
    size Int64,
    event_count Int64,
    message_count Int64,
    snapshot_source LowCardinality(Nullable(String))
) ENGINE = {engine}
"""

# if updating these column definitions
# you'll need to update the explicit column definitions in the materialized view creation statement below
SESSION_REPLAY_EVENTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id VARCHAR,
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    first_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    click_count SimpleAggregateFunction(sum, Int64),
    keypress_count SimpleAggregateFunction(sum, Int64),
    mouse_activity_count SimpleAggregateFunction(sum, Int64),
    active_milliseconds SimpleAggregateFunction(sum, Int64),
    console_log_count SimpleAggregateFunction(sum, Int64),
    console_warn_count SimpleAggregateFunction(sum, Int64),
    console_error_count SimpleAggregateFunction(sum, Int64),
    -- this column allows us to estimate the amount of data that is being ingested
    size SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of messages received in a session
    -- often very useful in incidents or debugging
    message_count SimpleAggregateFunction(sum, Int64),
    -- this allows us to count the number of snapshot events received in a session
    -- often very useful in incidents or debugging
    -- because we batch events we expect message_count to be lower than event_count
    event_count SimpleAggregateFunction(sum, Int64),
    -- which source the snapshots came from Android, iOS, Mobile, Web. Web if absent
    snapshot_source AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
    _timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = {engine}
"""

SESSION_REPLAY_EVENTS_DATA_TABLE_ENGINE = lambda: AggregatingMergeTree(
    "session_replay_events", replication_scheme=ReplicationScheme.SHARDED
)

SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    SESSION_REPLAY_EVENTS_TABLE_BASE_SQL
    + """
    PARTITION BY toYYYYMM(min_first_timestamp)
    -- order by is used by the aggregating merge tree engine to
    -- identify candidates to merge, e.g. toDate(min_first_timestamp)
    -- would mean we would have one row per day per session_id
    -- if CH could completely merge to match the order by
    -- it is also used to organise data to make queries faster
    -- we want the fewest rows possible but also the fastest queries
    -- since we query by date and not by time
    -- and order by must be in order of increasing cardinality
    -- so we order by date first, then team_id, then session_id
    -- hopefully, this is a good balance between the two
    ORDER BY (toDate(min_first_timestamp), team_id, session_id)
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

SESSION_REPLAY_EVENTS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS session_replay_events_mv ON CLUSTER '{cluster}'
TO {database}.{target_table} {explictly_specify_columns}
AS SELECT
session_id,
team_id,
any(distinct_id) as distinct_id,
min(first_timestamp) AS min_first_timestamp,
max(last_timestamp) AS max_last_timestamp,
-- TRICKY: ClickHouse will pick a relatively random first_url
-- when it collapses the aggregating merge tree
-- unless we teach it what we want...
-- argMin ignores null values
-- so this will get the first non-null value of first_url
-- for each group of session_id and team_id
-- by min of first_timestamp in the batch
-- this is an aggregate function, not a simple aggregate function
-- so we have to write to argMinState, and query with argMinMerge
argMinState(first_url, first_timestamp) as first_url,
sum(click_count) as click_count,
sum(keypress_count) as keypress_count,
sum(mouse_activity_count) as mouse_activity_count,
sum(active_milliseconds) as active_milliseconds,
sum(console_log_count) as console_log_count,
sum(console_warn_count) as console_warn_count,
sum(console_error_count) as console_error_count,
sum(size) as size,
-- we can count the number of kafka messages instead of sending it explicitly
sum(message_count) as message_count,
sum(event_count) as event_count,
argMinState(snapshot_source, first_timestamp) as snapshot_source,
max(_timestamp) as _timestamp
FROM {database}.kafka_session_replay_events
group by session_id, team_id
""".format(
        target_table="writable_session_replay_events",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
        # ClickHouse is incorrectly expanding the type of the snapshot source column
        # Despite it being a LowCardinality(Nullable(String)) in writable_session_replay_events
        # The column expansion picks only Nullable(String) and so we can't select it
        explictly_specify_columns="""(
`session_id` String, `team_id` Int64, `distinct_id` String,
`min_first_timestamp` DateTime64(6, 'UTC'),
`max_last_timestamp` DateTime64(6, 'UTC'),
`first_url` AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
`click_count` Int64, `keypress_count` Int64,
`mouse_activity_count` Int64, `active_milliseconds` Int64,
`console_log_count` Int64, `console_warn_count` Int64,
`console_error_count` Int64, `size` Int64, `message_count` Int64,
`event_count` Int64,
`snapshot_source` AggregateFunction(argMin, LowCardinality(Nullable(String)), DateTime64(6, 'UTC')),
`_timestamp` Nullable(DateTime)
)""",
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_session_replay_events based on a sharding key.
WRITABLE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    table_name="writable_session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)

# This table is responsible for reading from session_replay_events on a cluster setting
DISTRIBUTED_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: SESSION_REPLAY_EVENTS_TABLE_BASE_SQL.format(
    table_name="session_replay_events",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSION_REPLAY_EVENTS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)

DROP_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL = lambda: (
    f"TRUNCATE TABLE IF EXISTS {SESSION_REPLAY_EVENTS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)
