from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_BOUNCES_COMBINED_VIEW_SQL,
)

operations = [
    # Create daily tables
    run_sql_with_exceptions(WEB_STATS_DAILY_SQL()),
    run_sql_with_exceptions(WEB_BOUNCES_DAILY_SQL()),
    # Create hourly tables
    run_sql_with_exceptions(WEB_STATS_HOURLY_SQL()),
    run_sql_with_exceptions(WEB_BOUNCES_HOURLY_SQL()),
    # Create staging tables for hourly processing
    run_sql_with_exceptions(WEB_STATS_HOURLY_SQL().replace("web_stats_hourly", "web_stats_hourly_staging")),
    run_sql_with_exceptions(WEB_BOUNCES_HOURLY_SQL().replace("web_bounces_hourly", "web_bounces_hourly_staging")),
    # Create combined views that merge daily and hourly data
    run_sql_with_exceptions(WEB_STATS_COMBINED_VIEW_SQL()),
    run_sql_with_exceptions(WEB_BOUNCES_COMBINED_VIEW_SQL()),
]
