# Table for storing lazy-precomputed web stats FRUSTRATION metrics
# (rage clicks, dead clicks, exceptions).
#
# One row per (team, job, UTC hour, breakdown_value). The strategy that drives
# the frustration tile groups events per session × breakdown_value, then sums
# the per-session counts across sessions. Each session is attributed to its
# `min(session.$start_timestamp)` hour; rows from the same hour for the same
# breakdown_value are summed via `sumMerge` at read time.
#
# `breakdown_value` is whatever the runner's `_counts_breakdown_value()` emits
# (typically the URL pathname for the only breakdown the frustration tile ships
# today). The choice of `breakdown_by` is encoded into the INSERT AST and
# therefore into the lazy_computation cache key — different `breakdown_by`
# values become distinct precompute jobs, so storing the discriminator in the
# row is unnecessary.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_stats_frustration_preaggregated"


def DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket. Reads filter by [window_start_utc, window_end_utc).
    time_window_start DateTime64(6, 'UTC'),

    -- Breakdown value emitted by the strategy (URL path, etc.). The choice of
    -- `breakdown_by` is part of the cache key, not stored here.
    breakdown_value String,

    -- Per-hour per-breakdown sums of session-level event counts (matching the
    -- FRUSTRATION_METRICS_INNER_QUERY semantics: countIf at the session level,
    -- summed across sessions in the outer query).
    sum_rage_clicks_state AggregateFunction(sum, Int64),
    sum_dead_clicks_state AggregateFunction(sum, Int64),
    sum_errors_state AggregateFunction(sum, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` so `ttl_only_drop_parts=1` can drop whole parts
    # atomically as soon as all rows in them expire. Mixed-TTL writes (15m for
    # today, 7d for older) land in distinct parts and the short-TTL parts drop
    # cleanly.
    #
    # ORDER BY puts `breakdown_value` ahead of `time_window_start` because the
    # read query's outer `GROUP BY breakdown_value` benefits from co-locating
    # rows for a given breakdown. One `job_id` covers exactly one UTC day, so
    # rows under a matched job are within the read's `[cur_start, cur_end)`
    # range already — `time_window_start` is a tiebreaker, not a prune key.
    return (
        WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, breakdown_value, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL():
    return WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_STATS_FRUSTRATION_PREAGGREGATED_TABLE()}"
