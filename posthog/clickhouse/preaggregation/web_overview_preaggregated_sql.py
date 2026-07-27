# Table for storing lazy-precomputed web overview aggregates
#
# Stores per-hour, per-team aggregate states for the five metrics surfaced by
# WebOverviewQueryRunner: unique users, unique sessions, total pageviews,
# average session duration, average bounce rate. Reads merge across hourly
# buckets to answer arbitrary date ranges within the precomputed window.
#
# Buckets are UTC hourly so reads stay correct for any whole-hour-offset team
# timezone without storing per-team-tz data.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_overview_preaggregated"


def DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_OVERVIEW_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket. Reads filter by [window_start_utc, window_end_utc).
    time_window_start DateTime64(6, 'UTC'),

    -- Aggregate states matching WebOverviewQueryRunner.outer_select metrics.
    -- `uniq` (HyperLogLog) is used over `uniqExact` because HogQL exposes
    -- `uniqMergeIf` but not `uniqExactMergeIf`, and ~99% accuracy is fine for the
    -- dashboard use case (matches the v2 pre-aggregation choice).
    uniq_users_state AggregateFunction(uniq, UUID),
    uniq_sessions_state AggregateFunction(uniq, String),
    sum_pageviews_state AggregateFunction(sum, Int64),
    avg_duration_state AggregateFunction(avg, Float64),
    avg_bounce_state AggregateFunction(avg, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` can
    # actually drop whole parts atomically when all rows in them expire. Rows
    # for the same UTC day share a partition regardless of which `time_window_start`
    # hour they cover, so mixed-TTL writes (15m for today, 7d for older) end up
    # in distinct parts and the short-TTL parts drop cleanly.
    return (
        WEB_OVERVIEW_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events
    # data nodes — the precompute table is small and read by a narrow set of
    # queries that never JOIN against events). Distributed read table lives
    # on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_OVERVIEW_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_OVERVIEW_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}"
