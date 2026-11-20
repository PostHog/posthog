from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_CHANNEL_TYPE = "ADD COLUMN IF NOT EXISTS channel_type LowCardinality(String) AFTER mat_metadata_loggedIn"

BOUNCES_ORDER_BY = (
    "team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, "
    "viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, "
    "utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, "
    "has_fbclid, mat_metadata_backend, mat_metadata_loggedIn, channel_type"
)

STATS_ORDER_BY = (
    "team_id, job_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, "
    "viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, "
    "utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, "
    "has_fbclid, mat_metadata_backend, mat_metadata_loggedIn, channel_type"
)

# The tables are ReplacingMergeTree, so a merge keeps one row per sorting key. Two rows that differ only by
# channel_type (a custom rule on the entry URL can split otherwise equal sessions) would collapse into one
# unless the column is part of the key. ClickHouse can add a new column to the end of the sorting key only
# in the ALTER that adds the column. The primary key does not change, so existing parts stay valid.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_web_stats_dimensional_preaggregated {ADD_CHANNEL_TYPE}, "
        f"MODIFY ORDER BY ({STATS_ORDER_BY})",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_web_bounces_dimensional_preaggregated {ADD_CHANNEL_TYPE}, "
        f"MODIFY ORDER BY ({BOUNCES_ORDER_BY})",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    *(
        run_sql_with_exceptions(
            f"ALTER TABLE {table} {ADD_CHANNEL_TYPE}",
            node_roles=[role],
            sharded=False,
            is_alter_on_replicated_table=False,
        )
        for table in ("web_stats_dimensional_preaggregated", "web_bounces_dimensional_preaggregated")
        for role in (NodeRole.DATA, NodeRole.AUX)
    ),
]
