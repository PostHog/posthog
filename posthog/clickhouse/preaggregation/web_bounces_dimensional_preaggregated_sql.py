# Table for storing scheduled-precomputed web bounce metrics with fixed dimensions.
#
# Precomputation-framework successor to the v2 pre-aggregation table
# `web_pre_aggregated_bounces`. Same fixed dimension set as the stats table minus
# `pathname` (bounces are attributed per session, not per pathname), plus the
# bounce/duration/session-count aggregate states. See
# `web_stats_dimensional_preaggregated_sql.py` for the framework column-injection
# notes (team_id/job_id/expires_at are added automatically; computed_at defaults).

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree, ReplicationScheme

TABLE_BASE_NAME = "web_bounces_dimensional_preaggregated"


def DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED, ver="computed_at")


WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    -- Hourly UTC bucket on the session's start timestamp (matches v2 `period_bucket`).
    period_bucket DateTime,

    -- Fixed dimensions — identical set to v2 `web_pre_aggregated_bounces`.
    host String,
    device_type String,
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

    -- Aggregate states for bounce-rate and session-duration metrics.
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, Int64),
    bounces_count_state AggregateFunction(sum, Int64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_session_count_state AggregateFunction(sum, Int64),

    -- ReplacingMergeTree version column: latest INSERT wins on duplicate ORDER BY keys.
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- Sub-day precision so the framework can attach short TTLs to recent windows.
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    # See the stats table for the partitioning / ORDER BY / nullable-key rationale.
    return (
        WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (
    team_id,
    job_id,
    period_bucket,
    host,
    device_type,
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
        table_name=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE()}"


def DROP_SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE()} SYNC"


def TRUNCATE_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE()}"
