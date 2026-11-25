from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_HOSTS = "ADD COLUMN IF NOT EXISTS session_hosts Array(String) AFTER channel_type"
ADD_BOUNCE_ELIGIBLE_SESSIONS = (
    "ADD COLUMN IF NOT EXISTS bounce_eligible_sessions_state AggregateFunction(sum, Int64) "
    "AFTER total_session_count_state"
)

BOUNCES_ORDER_BY = (
    "team_id, job_id, period_bucket, host, device_type, entry_pathname, end_pathname, browser, os, "
    "viewport_width, viewport_height, referring_domain, utm_source, utm_medium, utm_campaign, utm_term, "
    "utm_content, country_code, city_name, region_code, region_name, has_gclid, has_gad_source_paid_search, "
    "has_fbclid, mat_metadata_backend, mat_metadata_loggedIn, channel_type, session_hosts"
)

# The table is ReplacingMergeTree, so a merge keeps one row per sorting key. Two rows of one job that differ only
# by session_hosts (sessions with the same dimensions that viewed different hosts) would collapse into one unless the
# column is part of the key. ClickHouse can add a new column to the end of the sorting key only in the ALTER that
# adds the column. The primary key does not change, so existing parts stay valid.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE sharded_web_bounces_dimensional_preaggregated {ADD_HOSTS}, {ADD_BOUNCE_ELIGIBLE_SESSIONS}, "
        f"MODIFY ORDER BY ({BOUNCES_ORDER_BY})",
        node_roles=[NodeRole.AUX],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    *(
        run_sql_with_exceptions(
            f"ALTER TABLE web_bounces_dimensional_preaggregated {ADD_HOSTS}, {ADD_BOUNCE_ELIGIBLE_SESSIONS}",
            node_roles=[role],
            sharded=False,
            is_alter_on_replicated_table=False,
        )
        for role in (NodeRole.DATA, NodeRole.AUX)
    ),
]
