# Reusable cost precompute: marketing source cost rows (per source, campaign, ad_group, ad, day)
# materialized out of the external data-warehouse tables (S3) into native ClickHouse. The cost side
# of marketing analytics is a `UNION ALL` of N source adapters reading S3-backed DWH tables; that S3
# read is the dashboard's variable cold-cache bottleneck. This caches the normalized cost rows at fine
# (ad-level) grain — one lazy job per source — so the dashboard reads native CH and every drill-down
# (campaign/source/ad_group/ad) is a GROUP BY over the same table. Sibling of the touchpoints/conversions
# preagg tables.


TABLE_BASE_NAME = "marketing_costs_preaggregated"


def DISTRIBUTED_MARKETING_COSTS_TABLE():
    return TABLE_BASE_NAME
