from django.conf import settings

from posthog.clickhouse.kafka_engine import kafka_engine
from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    AggregatingMergeTree,
)
from posthog.kafka_client.topics import KAFKA_SESSIONS

SESSIONS_DATA_TABLE = lambda: "sharded_sessions"

"""
Kafka needs slightly different column setup. It receives individual events, not aggregates.
We write first_timestamp and last_timestamp as individual records
They will be grouped as min_first_timestamp and max_last_timestamp in the main table
"""
KAFKA_SESSIONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    first_timestamp DateTime64(6, 'UTC'),
    last_timestamp DateTime64(6, 'UTC'),

    urls Array(VARCHAR),
    entry_url Nullable(VARCHAR),
    exit_url Nullable(VARCHAR),
    initial_utm_source Nullable(VARCHAR),
    initial_utm_campaign Nullable(VARCHAR),
    initial_utm_medium Nullable(VARCHAR),
    initial_utm_term Nullable(VARCHAR),
    initial_utm_content Nullable(VARCHAR),
    initial_referring_domain Nullable(VARCHAR),

    event_count Int64,
    pageview_count Int64
) ENGINE = {engine}
"""

# if updating these column definitions
# you'll need to update the explicit column definitions in the materialized view creation statement below
SESSIONS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
(
    -- part of order by so will aggregate correctly
    session_id VARCHAR,
    -- part of order by so will aggregate correctly
    team_id Int64,
    -- ClickHouse will pick any value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    min_first_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_last_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    urls AggregateFunction(groupArrayIf(1000), Nullable(String), UInt8),
    entry_url AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    exit_url AggregateFunction(argMax, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_utm_source AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_utm_campaign AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_utm_medium AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_utm_term AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_utm_content AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),
    initial_referring_domain AggregateFunction(argMin, Nullable(VARCHAR), DateTime64(6, 'UTC')),

    event_count SimpleAggregateFunction(sum, Int64),
    pageview_count SimpleAggregateFunction(sum, Int64),
    _timestamp SimpleAggregateFunction(max, DateTime)
) ENGINE = {engine}
"""

SESSIONS_DATA_TABLE_ENGINE = lambda: AggregatingMergeTree("sessions", replication_scheme=ReplicationScheme.SHARDED)

SESSIONS_TABLE_SQL = lambda: (
    SESSIONS_TABLE_BASE_SQL
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
    table_name=SESSIONS_DATA_TABLE(),
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=SESSIONS_DATA_TABLE_ENGINE(),
)

KAFKA_SESSIONS_TABLE_SQL = lambda: KAFKA_SESSIONS_TABLE_BASE_SQL.format(
    table_name="kafka_sessions",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=kafka_engine(topic=KAFKA_SESSIONS),
)

SESSIONS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS sessions_mv ON CLUSTER '{cluster}'
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

groupArray(urls) AS urls
argMinState(entry_url, first_timestamp) as entry_url,
argMaxState(exit_url, last_timstamp) as exit_url,
argMinState(initial_utm_source, first_timestamp) as initial_utm_source,
argMinState(initial_utm_campaign, first_timestamp) as initial_utm_campaign,
argMinState(initial_utm_medium, first_timestamp) as initial_utm_medium,
argMinState(initial_utm_term, first_timestamp) as initial_utm_term,
argMinState(initial_utm_content, first_timestamp) as initial_utm_content,
argMinState(initial_referring_domain, first_timestamp) as initial_referring_domain,
sum(event_count) as event_count,
sum(pageview_count) as pageview_count,

FROM {database}.kafka_sessions
group by session_id, team_id
""".format(
        target_table="writable_sessions",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
        # ClickHouse is incorrectly expanding the type of the snapshot source column
        # Despite it being a LowCardinality(Nullable(String)) in writable_sessions
        # The column expansion picks only Nullable(String) and so we can't select it
        explictly_specify_columns="""(
)""",
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.
WRITABLE_SESSIONS_TABLE_SQL = lambda: SESSIONS_TABLE_BASE_SQL.format(
    table_name="writable_sessions",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSIONS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)

# This table is responsible for reading from sessions on a cluster setting
DISTRIBUTED_SESSIONS_TABLE_SQL = lambda: SESSIONS_TABLE_BASE_SQL.format(
    table_name="sessions",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSIONS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)

DROP_SESSIONS_TABLE_SQL = lambda: (
    f"DROP TABLE IF EXISTS {SESSIONS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)

TRUNCATE_SESSIONS_TABLE_SQL = lambda: (
    f"TRUNCATE TABLE IF EXISTS {SESSIONS_DATA_TABLE()} ON CLUSTER '{settings.CLICKHOUSE_CLUSTER}'"
)
