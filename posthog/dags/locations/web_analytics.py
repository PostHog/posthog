import dagster

from posthog.settings import TEST

from products.web_analytics.dags import (
    cache_favicons,
    cache_warming,
    web_pre_aggregated_accuracy,
    web_preaggregated,
    web_preaggregated_asset_checks,
    web_preaggregated_team_selection,
)

from . import resources

# Build schedules list conditionally based on TEST mode
schedules = [
    web_preaggregated.web_pre_aggregate_historical_schedule,
    web_preaggregated.web_pre_aggregate_current_day_schedule,
    cache_warming.web_analytics_cache_warming_schedule,
    cache_favicons.cache_authorized_domain_favicons_schedule,
]

# Only include the backfill schedule when not in TEST mode
# as it accesses Dagster instance methods that may not be initialized during tests
if not TEST:
    schedules.append(web_preaggregated.web_analytics_v2_backfill_schedule)

defs = dagster.Definitions(
    assets=[
        web_preaggregated_team_selection.web_analytics_team_selection,
        web_preaggregated.web_pre_aggregated_bounces,
        web_preaggregated.web_pre_aggregated_stats,
        web_pre_aggregated_accuracy.web_pre_aggregated_accuracy,
        cache_favicons.cache_favicons,
        cache_favicons.cache_authorized_domain_favicons,
    ],
    asset_checks=[
        web_preaggregated_asset_checks.web_analytics_team_selection_has_data,
    ],
    jobs=[
        web_preaggregated.web_pre_aggregate_job,
        cache_warming.web_analytics_cache_warming_job,
        cache_favicons.cache_authorized_domain_favicons_job,
    ],
    schedules=schedules,
    resources=resources,
)
