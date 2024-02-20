from django.conf import settings

from posthog.clickhouse.table_engines import (
    Distributed,
    ReplicationScheme,
    AggregatingMergeTree,
)

TABLE_BASE_NAME = "sessions_test"
SESSIONS_DATA_TABLE = lambda: f"sharded_{TABLE_BASE_NAME}"

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

    urls SimpleAggregateFunction(groupUniqArrayArray, Array(VARCHAR)),
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

SESSIONS_DATA_TABLE_ENGINE = lambda: AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)

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

SESSIONS_TABLE_MV_SQL = (
    lambda: """
CREATE MATERIALIZED VIEW IF NOT EXISTS {table_name} ON CLUSTER '{cluster}'
TO {database}.{target_table}
AS SELECT
$session_id as session_id,
team_id,
any(distinct_id) as distinct_id,
min(timestamp) AS min_first_timestamp,
max(timestamp) AS max_last_timestamp,
-- TRICKY: ClickHouse will pick a relatively random "entry"
-- when it collapses the aggregating merge tree
-- unless we teach it what we want...
-- argMin ignores null values
-- so this will get the first non-null value of "entry"
-- for each group of session_id and team_id
-- by min of first_timestamp in the batch
-- this is an aggregate function, not a simple aggregate function
-- so we have to write to argMinState, and query with argMinMerge

groupUniqArray(JSONExtractString(properties, '$current_url')) AS urls,
argMinState(JSONExtractString(properties, '$current_url'), timestamp) as entry_url,
argMaxState(JSONExtractString(properties, '$current_url'), timestamp) as exit_url,
argMinState(JSONExtractString(properties, '$initial_utm_source'), timestamp) as initial_utm_source,
argMinState(JSONExtractString(properties, '$initial_utm_campaign'), timestamp) as initial_utm_campaign,
argMinState(JSONExtractString(properties, '$initial_utm_medium'), timestamp) as initial_utm_medium,
argMinState(JSONExtractString(properties, '$initial_utm_term'), timestamp) as initial_utm_term,
argMinState(JSONExtractString(properties, '$initial_utm_content'), timestamp) as initial_utm_content,
argMinState(JSONExtractString(properties, '$initial_referring_domain'), timestamp) as initial_referring_domain,
count(*) as event_count,
sumIf(1, event='$pageview') as pageview_count

FROM {database}.events
group by session_id, team_id
""".format(
        table_name=f"{TABLE_BASE_NAME}_mv",
        target_table=f"writable_{TABLE_BASE_NAME}",
        cluster=settings.CLICKHOUSE_CLUSTER,
        database=settings.CLICKHOUSE_DATABASE,
    )
)

# Distributed engine tables are only created if CLICKHOUSE_REPLICATED

# This table is responsible for writing to sharded_sessions based on a sharding key.
WRITABLE_SESSIONS_TABLE_SQL = lambda: SESSIONS_TABLE_BASE_SQL.format(
    table_name=f"writable_{TABLE_BASE_NAME}",
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSIONS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)

# This table is responsible for reading from sessions on a cluster setting
DISTRIBUTED_SESSIONS_TABLE_SQL = lambda: SESSIONS_TABLE_BASE_SQL.format(
    table_name=TABLE_BASE_NAME,
    cluster=settings.CLICKHOUSE_CLUSTER,
    engine=Distributed(
        data_table=SESSIONS_DATA_TABLE(),
        sharding_key="sipHash64(distinct_id)",
    ),
)
