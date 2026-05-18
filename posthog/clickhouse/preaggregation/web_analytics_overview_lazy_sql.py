# Lazy-computation table for the web analytics overview tile.
#
# WebOverview returns a single-row scalar response (visitors, views, sessions,
# avg session duration, bounce rate), so the cache shape can be very narrow:
# per-(team, time_window, filter_set) aggregate states — no breakdown dimension.
#
# Filters are baked into the INSERT WHERE and therefore into the cache key
# (via the AST hash). Each unique filter combination produces a separate row
# per daily window. Readback is trivial: sumMergeIf / uniqMergeIf with just the
# time_window filter.

from posthog.clickhouse.table_engines import AggregatingMergeTree, Distributed, ReplicationScheme

TABLE_BASE_NAME = "web_analytics_overview_lazy"


def DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE():
    return TABLE_BASE_NAME


def SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_ENGINE():
    return AggregatingMergeTree(TABLE_BASE_NAME, replication_scheme=ReplicationScheme.SHARDED)


WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- Aggregate states (merged at readback with sumMergeIf / uniqMergeIf).
    -- Mirrors the schema of `web_pre_aggregated_bounces` so the existing
    -- WebOverviewPreAggregatedQueryBuilder semantics carry over directly.
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, UInt64),
    bounces_count_state AggregateFunction(sum, UInt64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_session_count_state AggregateFunction(sum, UInt64),

    -- TTL: rows are automatically deleted during parts merges after expires_at
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL():
    return (
        WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, time_window_start)
TTL expires_at
SETTINGS index_granularity=8192
"""
    ).format(
        table_name=SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE(),
        engine=SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL():
    return WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE(),
            sharding_key="sipHash64(job_id)",
        ),
    )


def DROP_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE()}"


def DROP_SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE()} SYNC"


def TRUNCATE_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_WEB_ANALYTICS_OVERVIEW_LAZY_TABLE()}"
