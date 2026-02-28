# Generalized preaggregation table for product analytics queries (trends, retention, funnels)
#
# Key differences from v1 (preaggregation_results):
# - Uses uniq (HyperLogLog, ~2% error) instead of uniqExact for automatic mode
# - Stores multiple aggregate state columns for different math types
# - Includes event name as a dimension, enabling multi-event precomputation
# - Hourly granularity for flexible interval rollup (hour -> day -> week -> month)
#
# This table is designed for the "automatic" lazy precomputation mode where
# imprecise calculations are acceptable in exchange for faster queries.

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "preaggregation_v2"


def DISTRIBUTED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- TTL
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY,

    -- Dimensions
    event String DEFAULT '',
    breakdown_value Array(String) DEFAULT [],

    -- Aggregate states: each precomputation populates only the columns it needs.
    -- Unused columns are empty aggregate states (zero-cost in AggregatingMergeTree).

    -- Event count: sumState(1) per event, merge with sumMerge for totals
    count_state AggregateFunction(sum, UInt64),

    -- Unique actors (approximate, HyperLogLog): uniqState(person_id)
    uniq_persons_state AggregateFunction(uniq, UUID),

    -- Unique sessions (approximate): uniqState($session_id)
    uniq_sessions_state AggregateFunction(uniq, String),

    -- Numeric property aggregations
    sum_state AggregateFunction(sum, Float64),
    min_state AggregateFunction(min, Float64),
    max_state AggregateFunction(max, Float64),

    -- For computing averages: avg = sum / count
    -- count_state already provides the denominator

    -- Theta sketch for set intersection (retention cohort analysis)
    -- uniqTheta supports bitmapAnd for set intersection
    uniq_theta_state AggregateFunction(uniqTheta, UUID)
) ENGINE = {engine}
"""


def SHARDED_TABLE_SQL():
    return (
        TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, event, time_window_start, breakdown_value)
TTL expires_at
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_TABLE(),
        engine=SHARDED_TABLE_ENGINE(),
    )


def DISTRIBUTED_TABLE_SQL():
    return TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_TABLE(),
            sharding_key="sipHash64(job_id)",
        ),
    )


def DROP_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_TABLE()}"


def DROP_SHARDED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_TABLE()} SYNC"


def TRUNCATE_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_TABLE()}"
