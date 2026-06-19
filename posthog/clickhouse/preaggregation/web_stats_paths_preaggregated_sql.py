# Table for storing lazy-precomputed web stats PATHS aggregates (path tile
# with bounce rate).
#
# One row per (team, job, UTC hour, breakdown_value) where breakdown_value is
# the URL path (optionally prepended with host). For each session, we emit one
# row per pathname it touched. The bounce aggregate is set only when the
# pathname matched the session's entry pathname, which avgState ignores via
# NULL on other rows — that matches the v2 PATH_BOUNCE_QUERY semantic of
# attributing bounce to sessions that entered on the path.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_stats_paths_preaggregated"


def DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_STATS_PATHS_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket. Reads filter by [window_start_utc, window_end_utc).
    time_window_start DateTime64(6, 'UTC'),

    -- URL path the row aggregates. Optionally prefixed with `$host` when the
    -- query has `includeHost=True`; the includeHost flag is in the cache key
    -- via placeholder hashing so cleaned-vs-raw / hosted-vs-not are distinct
    -- precomputes.
    breakdown_value String,

    -- Per-pathname counts: persons that touched this pathname, and total
    -- pageview events on this pathname.
    uniq_users_state AggregateFunction(uniq, UUID),
    sum_pageviews_state AggregateFunction(sum, Int64),

    -- Bounce rate is set only when pathname matched the session's entry
    -- pathname — other contributions are NULL, which avgState ignores.
    -- This reproduces the v2 PATH_BOUNCE_QUERY join semantic without a JOIN
    -- at read time. The state type is `Nullable(Float64)` so the conditional
    -- `if(..., is_bounce, NULL)` in the INSERT matches the column type.
    avg_bounce_state AggregateFunction(avg, Nullable(Float64)),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` so `ttl_only_drop_parts=1` can drop whole parts
    # atomically as soon as all rows in them expire. Mixed-TTL writes (15m for
    # today, 7d for older) land in distinct parts and the short-TTL parts drop
    # cleanly.
    #
    # ORDER BY puts `breakdown_value` ahead of `time_window_start` because the
    # read query's outer `GROUP BY breakdown_value` benefits from co-locating
    # rows for a given path. One `job_id` covers exactly one UTC day, so rows
    # under a matched job are within the read's `[cur_start, cur_end)` range
    # already — `time_window_start` is a tiebreaker, not a prune key.
    return (
        WEB_STATS_PATHS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, breakdown_value, time_window_start)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL():
    return WEB_STATS_PATHS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_STATS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_STATS_PATHS_PREAGGREGATED_TABLE()}"


# --- Breakdown-key colocation layout (parallel experiment for the PATHS tile;
# see lazy_computation/CONSISTENCY.md). Same columns as the table above, but the
# breakdown (path) drives both the sort key and the shard key, so high-cardinality
# reads stay local and aggregate in parallel. Kept as a parallel table so the lazy
# paths runner can A/B it against the original before we commit.
#
# Two changes vs the table above, both targeting the read:
#   1. ORDER BY leads with `time_window_start` then `breakdown_value` (job_id
#      moves to last). A time-range read range-skips via the primary index and
#      the outer `GROUP BY breakdown_value` reads co-located rows — mirroring v2
#      `web_pre_aggregated_stats`, where `pathname` sits high in the sort key and
#      a 30d read finishes in ~100ms. The original leads with the random `job_id`
#      UUID, so `job_id IN (...)` seeks scattered key ranges.
#   2. Sharded by `sipHash64(breakdown_value)` instead of `sipHash64(job_id)`, so
#      a single large job's paths spread across shards and the read fans out to
#      aggregate in parallel — instead of pinning the whole job to one shard. See
#      the "shard by breakdown_value" note in lazy_computation/CONSISTENCY.md.
#
# Partitioning/TTL stay on `expires_at` so short-TTL recomputes still drop in
# whole parts (read locality must not reintroduce stale-recompute scans).
TABLE_PATHKEY_BASE_NAME = "web_stats_paths_preaggregated_pathkey"


def DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE():
    return TABLE_PATHKEY_BASE_NAME


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE():
    return f"sharded_{TABLE_PATHKEY_BASE_NAME}"


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_PATHKEY_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


def SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL():
    return (
        WEB_STATS_PATHS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, time_window_start, breakdown_value, job_id)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE(),
        engine=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL():
    return WEB_STATS_PATHS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE(),
            sharding_key="sipHash64(breakdown_value)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE()}"


def DROP_SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE()} SYNC"


def TRUNCATE_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_STATS_PATHS_PREAGGREGATED_PATHKEY_TABLE()}"
