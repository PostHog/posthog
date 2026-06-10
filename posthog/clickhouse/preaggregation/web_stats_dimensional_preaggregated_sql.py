# Table for storing scheduled-precomputed web stats with fixed dimensions.
#
# This is the precomputation-framework successor to the v2 pre-aggregation table
# `web_pre_aggregated_stats`. It carries the same fixed dimension set (host,
# device_type, pathname, browser, os, utm_*, geoip, …) baked into the schema, so
# reads answer breakdowns without filtering raw sessions/events. Unlike v2 it is
# populated through `ensure_precomputed` (job_id + TTL + ReplacingMergeTree)
# rather than a staging-table + partition-swap ETL, which removes the per-team
# backfill dance.
#
# The framework auto-injects `team_id` (first column), `job_id` (second) and
# `expires_at` (last) into every INSERT, and `computed_at` defaults on insert —
# so the INSERT SELECT only emits `period_bucket`, the dimensions and the
# aggregate states. INSERTs match columns by name, so table column order is free.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_stats_dimensional_preaggregated"


def DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket on the session's start timestamp (matches the v2
    -- pre-aggregation `period_bucket`). Reads filter by [window_start, window_end).
    period_bucket DateTime,

    -- Fixed dimensions — identical set to v2 `web_pre_aggregated_stats`.
    host String,
    device_type String,
    pathname String,
    entry_pathname String,
    end_pathname String,
    browser String,
    os String,
    viewport_width Int64,
    viewport_height Int64,
    referring_domain String,
    utm_source String,
    utm_medium String,
    utm_campaign String,
    utm_term String,
    utm_content String,
    country_code String,
    city_name String,
    region_code String,
    region_name String,
    has_gclid Bool,
    has_gad_source_paid_search Bool,
    has_fbclid Bool,
    -- EU-only custom metadata; NULL on US. Nullable so the US INSERT can emit NULL.
    mat_metadata_backend Nullable(String),
    mat_metadata_loggedIn Nullable(Bool),

    -- Aggregate states: unique persons, unique sessions and total pageviews.
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach short TTLs to recent windows.
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    # Partition by `expires_at` (the TTL column) so `ttl_only_drop_parts=1` drops
    # whole parts atomically once all their rows expire. `job_id` is in ORDER BY
    # so distinct compute jobs coexist (the read path filters to the fresh
    # job_ids); every dimension is in ORDER BY so the ReplacingMergeTree never
    # collapses rows that differ only by a dimension. `allow_nullable_key=1` lets
    # the nullable EU metadata columns participate in the sort key.
    return (
        WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (
    team_id,
    job_id,
    period_bucket,
    host,
    device_type,
    pathname,
    entry_pathname,
    end_pathname,
    browser,
    os,
    viewport_width,
    viewport_height,
    referring_domain,
    utm_source,
    utm_medium,
    utm_campaign,
    utm_term,
    utm_content,
    country_code,
    city_name,
    region_code,
    region_name,
    has_gclid,
    has_gad_source_paid_search,
    has_fbclid,
    mat_metadata_backend,
    mat_metadata_loggedIn
)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1, allow_nullable_key = 1
"""
    ).format(
        table_name=SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    # The sharded table lives on the AUX cluster (kept off the main events data
    # nodes — small table, never JOINed against events). Distributed read table
    # lives on DATA so queries fan out from there and resolve to AUX shards.
    return WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE()}"
