# Reusable cost precompute: marketing source cost rows (per source, campaign, ad_group, ad, day)
# materialized out of the external data-warehouse tables (S3) into native ClickHouse. The cost side
# of marketing analytics is a `UNION ALL` of N source adapters reading S3-backed DWH tables; that S3
# read is the dashboard's variable cold-cache bottleneck. This caches the normalized cost rows at fine
# (ad-level) grain — one lazy job per source — so the dashboard reads native CH and every drill-down
# (campaign/source/ad_group/ad) is a GROUP BY over the same table. Sibling of the touchpoints/conversions
# preagg tables.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

TABLE_BASE_NAME = "marketing_costs_preaggregated"


def DISTRIBUTED_MARKETING_COSTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_MARKETING_COSTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def SHARDED_MARKETING_COSTS_TABLE_ENGINE():
    return ReplacingMergeTree(TABLE_BASE_NAME, ver="computed_at")


MARKETING_COSTS_TABLE_BASE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name}
(
    team_id Int64,
    job_id UUID,

    source_id String,
    source_name String,
    grain LowCardinality(String),
    match_key String,
    campaign_id String,
    campaign_name String,
    ad_group_id String,
    ad_group_name String,
    ad_id String,
    ad_name String,
    cost_date Date,

    cost Float64,
    clicks Float64,
    impressions Float64,
    reported_conversions Float64,
    reported_conversion_value Float64,

    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {engine}
"""


def SHARDED_MARKETING_COSTS_TABLE_SQL():
    return (
        MARKETING_COSTS_TABLE_BASE_SQL
        + """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, source_name, grain, campaign_id, ad_group_id, ad_id, cost_date)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""
    ).format(
        table_name=SHARDED_MARKETING_COSTS_TABLE(),
        engine=SHARDED_MARKETING_COSTS_TABLE_ENGINE(),
    )


def DISTRIBUTED_MARKETING_COSTS_TABLE_SQL():
    return MARKETING_COSTS_TABLE_BASE_SQL.format(
        table_name=DISTRIBUTED_MARKETING_COSTS_TABLE(),
        engine=Distributed(
            data_table=SHARDED_MARKETING_COSTS_TABLE(),
            sharding_key="cityHash64(source_name, campaign_id)",
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def DROP_MARKETING_COSTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {DISTRIBUTED_MARKETING_COSTS_TABLE()}"


def DROP_SHARDED_MARKETING_COSTS_TABLE_SQL():
    return f"DROP TABLE IF EXISTS {SHARDED_MARKETING_COSTS_TABLE()} SYNC"


def TRUNCATE_MARKETING_COSTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_MARKETING_COSTS_TABLE()}"
