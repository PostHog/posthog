# Table for storing lazy-precomputed web vitals path-breakdown quantiles
#
# Stores per-day, per-team, per-path quantile-state aggregates matching
# `WebVitalsPathBreakdownQueryRunner`'s output. Reads merge across daily
# buckets and pick a single percentile (p75/p90/p99) via array indexing.
#
# Buckets are keyed by `toStartOfDay(event.timestamp, team_tz)` — the start
# of the team-local day (no session join in the raw query, so no session pad
# on the INSERT). One state column per Web Vitals metric (INP/LCP/CLS/FCP)
# — keeps the INSERT a single GROUP BY (vs. a discriminator column that
# would need ARRAY JOIN to fan out one event into four rows) and lets each
# metric tab read just one column.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_vitals_paths_preaggregated"


def DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_VITALS_PATHS_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Daily bucket keyed by `toStartOfDay(event.timestamp, team_tz)` — start
    -- of the team-local day. The raw vitals query has no session join, so no
    -- session-boundary pad is needed.
    time_window_start DateTime64(6, 'UTC'),

    -- Cleaned (or raw) `$pathname` — same expression the raw query uses, so
    -- post-cleaning paths land in the same row. Different `doPathCleaning`
    -- values hash to different cache keys via the placeholder substitution.
    path String,

    -- One reservoir per (path, day, metric) covering p75/p90/p99 in a single
    -- state. Reads pick a single percentile via
    -- `arrayElement(quantilesMergeIf(...), pct_index)`. Same reservoir
    -- algorithm as the raw `quantile(p)`; values match exactly when reservoir
    -- isn't saturated, within sampling noise once it is. Four columns instead
    -- of one row-per-metric keeps the INSERT a single GROUP BY without
    -- ARRAY JOIN, which is cheaper and avoids the new-analyzer's restriction
    -- on bare `events.properties` references in ARRAY JOIN source arrays.
    inp_quantiles_state AggregateFunction(quantiles(0.75, 0.90, 0.99), Float64),
    lcp_quantiles_state AggregateFunction(quantiles(0.75, 0.90, 0.99), Float64),
    cls_quantiles_state AggregateFunction(quantiles(0.75, 0.90, 0.99), Float64),
    fcp_quantiles_state AggregateFunction(quantiles(0.75, 0.90, 0.99), Float64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach TTLs like 15 min for "today".
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` can
    # drop whole parts atomically when all rows in them expire. `path` must be
    # in ORDER BY so the ReplacingMergeTree does not collapse distinct paths
    # within one (job, day).
    return (
        WEB_VITALS_PATHS_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, time_window_start, path)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events
    # data nodes — the precompute table is small and read by a narrow set of
    # queries that never JOIN against events). Distributed read table lives
    # on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_VITALS_PATHS_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_VITALS_PATHS_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_VITALS_PATHS_PREAGGREGATED_TABLE()}"
