from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_IS_TEST_ACCOUNT = "ADD COLUMN IF NOT EXISTS is_test_account Bool AFTER channel_type"

STATS_ADD_CLEANED_PATHS = (
    "ADD COLUMN IF NOT EXISTS pathname_cleaned String AFTER is_test_account, "
    "ADD COLUMN IF NOT EXISTS entry_pathname_cleaned String AFTER pathname_cleaned, "
    "ADD COLUMN IF NOT EXISTS end_pathname_cleaned String AFTER entry_pathname_cleaned"
)

BOUNCES_ADD_CLEANED_PATHS = (
    "ADD COLUMN IF NOT EXISTS entry_pathname_cleaned String AFTER is_test_account, "
    "ADD COLUMN IF NOT EXISTS end_pathname_cleaned String AFTER entry_pathname_cleaned"
)

BOUNCES_ORDER_BY = (
    "team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, "
    "viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, "
    "utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, "
    "has_fbclid, mat_metadata_backend, mat_metadata_loggedIn, channel_type, is_test_account"
)

STATS_ORDER_BY = (
    "team_id, job_id, period_bucket, host, device_type, pathname, entry_pathname, end_pathname, browser, os, "
    "viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, "
    "utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, "
    "has_fbclid, mat_metadata_backend, mat_metadata_loggedIn, channel_type, is_test_account"
)

# The tables are ReplacingMergeTree, so a merge keeps one row per sorting key. A test session and a real
# session with the same dimensions in the same hour would collapse into one row unless is_test_account is
# part of the key. ClickHouse can add a new column to the end of the sorting key only in the ALTER that
# adds the column. The cleaned path columns stay out of the key, because within one job they are a function
# of the raw path columns. The primary key does not change, so existing parts stay valid.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_web_stats_dimensional_preaggregated {ADD_IS_TEST_ACCOUNT}, "
        f"{STATS_ADD_CLEANED_PATHS}, MODIFY ORDER BY ({STATS_ORDER_BY})",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_web_bounces_dimensional_preaggregated {ADD_IS_TEST_ACCOUNT}, "
        f"{BOUNCES_ADD_CLEANED_PATHS}, MODIFY ORDER BY ({BOUNCES_ORDER_BY})",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    *(
        run_sql_with_exceptions(
            f"ALTER TABLE {table} {ADD_IS_TEST_ACCOUNT}, {cleaned_paths}",
            node_roles=[role],
            sharded=False,
            is_alter_on_replicated_table=False,
        )
        for table, cleaned_paths in (
            ("web_stats_dimensional_preaggregated", STATS_ADD_CLEANED_PATHS),
            ("web_bounces_dimensional_preaggregated", BOUNCES_ADD_CLEANED_PATHS),
        )
        for role in (NodeRole.DATA, NodeRole.AUX)
    ),
]
