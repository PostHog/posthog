import dagster

from dags import (
    web_pre_aggregated_accuracy,
    web_preaggregated,
    web_preaggregated_asset_checks,
    web_preaggregated_daily,
    web_preaggregated_hourly,
    web_preaggregated_team_selection,
)

from . import resources

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
    schedules=[
        web_preaggregated_daily.web_pre_aggregate_daily_schedule,
        web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_schedule,
        web_preaggregated.web_pre_aggregate_historical_schedule,
        web_preaggregated.web_pre_aggregate_current_day_schedule,
    ],
    resources=resources,
)
