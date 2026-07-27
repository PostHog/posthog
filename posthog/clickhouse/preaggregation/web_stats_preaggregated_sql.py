# Table for storing lazy-precomputed web stats table aggregates
#
# Stores per-hour, per-team, per-breakdown aggregate states for the two metrics
# surfaced by WebStatsTableQueryRunner's simple breakdowns: unique users and
# total pageviews. Reads merge across hourly buckets to answer arbitrary date
# ranges within the precomputed window.
#
# Shared by every low-cardinality simple breakdown and the channel-type
# breakdown — the `breakdown_by` column (a WebStatsBreakdown enum value) is the
# discriminator. Buckets are UTC hourly on the session's start timestamp, so the
# read matches the raw query's session-start attribution.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_stats_preaggregated"


def DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_STATS_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_STATS_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_STATS_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket on the session's start timestamp. Reads filter by
    -- [window_start_utc, window_end_utc).
    time_window_start DateTime64(6, 'UTC'),

    -- WebStatsBreakdown enum value (`Browser`, `Country`, `InitialChannelType`,
    -- ...). The discriminator that lets every simple breakdown share this table.
    breakdown_by String,

    -- The breakdown dimension value, JSON-encoded so tuple/float/null breakdowns
    -- (Region, City, Viewport, Timezone) round-trip through a single String column.
    breakdown_value String,

    -- Aggregate states matching WebStatsTableQueryRunner's simple-breakdown
    -- metrics: unique visitors and total pageviews. `uniq` (HyperLogLog) matches
    -- the v2 pre-aggregation choice; ~99% accuracy is fine for the table use case.
    -- Pageviews are counted per session in the INSERT, then summed here.
    uniq_users_state AggregateFunction(uniq, UUID),
    sum_pageviews_state AggregateFunction(sum, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_STATS_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` can
    # drop whole parts atomically when all rows in them expire. `breakdown_by` is
    # functionally constant per `job_id` but is kept in ORDER BY so the read-side
    # `WHERE breakdown_by = ...` filter is index-served; `breakdown_value` must be
    # in ORDER BY so the ReplacingMergeTree does not collapse distinct breakdown
    # values within one job.
    return (
        WEB_STATS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, breakdown_by, time_window_start, breakdown_value)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_STATS_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_STATS_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events
    # data nodes — the precompute table is small and read by a narrow set of
    # queries that never JOIN against events). Distributed read table lives
    # on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_STATS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_STATS_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_STATS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_STATS_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_STATS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_STATS_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_STATS_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_STATS_PREAGGREGATED_TABLE()}"
