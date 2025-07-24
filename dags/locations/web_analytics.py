import dagster

from . import resources

from dags import (
    web_preaggregated_asset_checks,
    web_preaggregated_daily,
    web_preaggregated_hourly,
    web_preaggregated_team_selection,
)

defs = dagster.Definitions(
    assets=[
        web_preaggregated_team_selection.web_analytics_team_selection,
        web_preaggregated_daily.web_stats_daily,
        web_preaggregated_daily.web_bounces_daily,
        web_preaggregated_daily.web_stats_daily_export,
        web_preaggregated_daily.web_bounces_daily_export,
        web_preaggregated_hourly.web_stats_hourly,
        web_preaggregated_hourly.web_bounces_hourly,
    ],
    asset_checks=[
        web_preaggregated_asset_checks.web_analytics_accuracy_check,
        web_preaggregated_asset_checks.stats_daily_has_data,
        web_preaggregated_asset_checks.stats_hourly_has_data,
        web_preaggregated_asset_checks.bounces_daily_has_data,
        web_preaggregated_asset_checks.bounces_hourly_has_data,
        web_preaggregated_asset_checks.stats_export_chdb_queryable,
        web_preaggregated_asset_checks.bounces_export_chdb_queryable,
    ],
    jobs=[
        web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_job,
        web_preaggregated_daily.web_pre_aggregate_daily_job,
        web_preaggregated_asset_checks.web_analytics_data_quality_job,
        web_preaggregated_asset_checks.simple_data_checks_job,
    ],
    schedules=[
        web_preaggregated_daily.web_pre_aggregate_daily_schedule,
        web_preaggregated_hourly.web_pre_aggregate_current_day_hourly_schedule,
        web_preaggregated_asset_checks.web_analytics_weekly_data_quality_schedule,
    ],
    resources=resources,
)
