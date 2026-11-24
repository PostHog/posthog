from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.web_bounces_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE,
    SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE,
    SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE,
)
from posthog.clickhouse.preaggregation.web_stats_dimensional_preaggregated_sql import (
    DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
    SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL,
)
from posthog.clickhouse.table_engines import Distributed

# The bounces tables as this migration first created them. Later migrations add columns and append them to
# the sorting key (0377 channel_type, 0395 hosts). ClickHouse appends a column to the sorting key only in the
# ALTER that adds it, so a fresh cluster must start from this shape, not from the current DDL. Otherwise 0377
# shortens the key of the current DDL and 0395 cannot append hosts again.
_BOUNCES_COLUMNS_AT_0272 = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,
    period_bucket DateTime,
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
    mat_metadata_backend Nullable(String),
    mat_metadata_loggedIn Nullable(Bool),
    persons_uniq_state AggregateFunction(uniq, UUID),
    sessions_uniq_state AggregateFunction(uniq, String),
    pageviews_count_state AggregateFunction(sum, Int64),
    bounces_count_state AggregateFunction(sum, Int64),
    total_session_duration_state AggregateFunction(sum, Int64),
    total_session_count_state AggregateFunction(sum, Int64),
    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY
) ENGINE = {engine}
"""

_BOUNCES_SHARDED_KEYS_AT_0272 = """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (
    team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os,
    viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term,
    utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search,
    has_fbclid, mat_metadata_backend, mat_metadata_loggedIn
)
TTL toDateTime(expires_at)
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1, allow_nullable_key = 1
"""


def SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return (_BOUNCES_COLUMNS_AT_0272 + _BOUNCES_SHARDED_KEYS_AT_0272).format(
        table_name=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_ENGINE(),
    )


def DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL():
    return _BOUNCES_COLUMNS_AT_0272.format(
        table_name=DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
        engine=Distributed(
            data_table=SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE(),
            sharding_key="sipHash64(job_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


operations = [
    # Sharded data tables on AUX (small fixed-dimension precompute tables, never
    # JOINed against events — kept off the main DATA cluster to avoid contention).
    run_sql_with_exceptions(
        SHARDED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        SHARDED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    # Distributed read tables on DATA — production query path fans out from data
    # nodes and resolves to AUX shards via the Distributed engine's `cluster=AUX`.
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Same distributed tables on AUX too, for ad-hoc debugging directly from an
    # AUX node (same DDL, no production cost).
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_STATS_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
]
