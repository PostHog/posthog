import dagster

from posthog.settings import TEST

from dags import (
    web_pre_aggregated_accuracy,
    web_preaggregated,
    web_preaggregated_asset_checks,
    web_preaggregated_daily,
    web_preaggregated_hourly,
    web_preaggregated_team_selection,
)

from . import resources

# Build schedules list conditionally based on TEST mode
schedules = [
    web_preaggregated_daily.web_pre_aggregate_daily_schedule,
    web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_schedule,
    web_preaggregated.web_pre_aggregate_historical_schedule,
    web_preaggregated.web_pre_aggregate_current_day_schedule,
]

# Only include the backfill schedule when not in TEST mode
# as it accesses Dagster instance methods that may not be initialized during tests
if not TEST:
    schedules.append(web_preaggregated.web_analytics_v2_backfill_schedule)

defs = dagster.Definitions(
    assets=[
        web_preaggregated_team_selection.web_analytics_team_selection,
        web_preaggregated_team_selection.web_analytics_team_selection_v2,
        web_preaggregated_daily.web_stats_daily,
        web_preaggregated_daily.web_bounces_daily,
        web_preaggregated_daily.web_stats_daily_export,
        web_preaggregated_daily.web_bounces_daily_export,
        web_preaggregated_hourly.web_stats_hourly,
        web_preaggregated_hourly.web_bounces_hourly,
        web_preaggregated.web_pre_aggregated_bounces,
        web_preaggregated.web_pre_aggregated_stats,
        web_pre_aggregated_accuracy.web_pre_aggregated_accuracy,
    ],
    asset_checks=[
        web_preaggregated_asset_checks.web_analytics_accuracy_check,
        web_preaggregated_asset_checks.web_analytics_team_selection_v2_has_data,
    ],
    jobs=[
        web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_job,
        web_preaggregated_daily.web_pre_aggregate_daily_job,
        web_preaggregated.web_pre_aggregate_job,
    ],
    schedules=schedules,
    resources=resources,
)
