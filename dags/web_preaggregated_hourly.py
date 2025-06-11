from datetime import datetime, UTC, timedelta
from collections.abc import Callable

import dagster
from dagster import Field, asset_check, AssetCheckResult, MetadataValue, AssetCheckSeverity
from dags.common import JobOwners
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS_HOURLY,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
)
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE, ClickhouseCluster


WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA = {
    **WEB_ANALYTICS_CONFIG_SCHEMA,
    "hours_back": Field(
        float,
        default_value=23,
        description="Number of hours back to process data for",
    ),
}


def pre_aggregate_web_analytics_hourly_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    extra_settings = config.get("extra_clickhouse_settings", "")
    hours_back = config["hours_back"]

    # Merge hourly settings with any extra settings
    clickhouse_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS_HOURLY, extra_settings)

    # Process the last N hours to handle any late-arriving data
    # Align with hour boundaries to match toStartOfHour() used in SQL, where we convert this to UTC,
    # so this is just to make sure we get complete hours
    now = datetime.now(UTC)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    date_end = (current_hour + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    date_start = (current_hour - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S")

    # Use a staging table to avoid downtime when swapping data
    staging_table_name = f"{table_name}_staging"

    # First, populate the staging table
    insert_query = sql_generator(
        date_start=date_start,
        date_end=date_end,
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=staging_table_name,
        granularity="hourly",
    )

    # First, make sure the staging table is empty
    sync_execute(f"TRUNCATE TABLE {staging_table_name} {ON_CLUSTER_CLAUSE(on_cluster=True)} SYNC")

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(f"Processing hourly data from {date_start} to {date_end}")
    context.log.info(insert_query)

    # Insert into staging table
    sync_execute(insert_query)

    # Truncate main table and insert from staging
    context.log.info(f"Swapping data from {staging_table_name} to {table_name}")
    sync_execute(f"TRUNCATE TABLE {table_name} {ON_CLUSTER_CLAUSE(on_cluster=True)} SYNC")
    sync_execute(f"INSERT INTO {table_name} SELECT * FROM {staging_table_name}")


@dagster.asset(
    name="web_analytics_bounces_hourly",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_tables"],
    metadata={"table": "web_bounces_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly bounce rate data for web analytics with 24h TTL. Updates every 5 minutes.
    """
    return pre_aggregate_web_analytics_hourly_data(
        context=context, table_name="web_bounces_hourly", sql_generator=WEB_BOUNCES_INSERT_SQL
    )


@dagster.asset(
    name="web_analytics_stats_table_hourly",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_tables"],
    metadata={"table": "web_stats_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly aggregated dimensional data with pageviews and unique user counts with 24h TTL. Updates every 5 minutes.
    """
    return pre_aggregate_web_analytics_hourly_data(
        context=context,
        table_name="web_stats_hourly",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


web_pre_aggregate_current_day_hourly_job = dagster.define_asset_job(
    name="web_pre_aggregate_current_day_hourly_job",
    selection=dagster.AssetSelection.assets(
        "web_analytics_bounces_hourly",
        "web_analytics_stats_table_hourly",
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="*/10 * * * *",
    job=web_pre_aggregate_current_day_hourly_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_current_day_hourly_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Creates real-time web analytics pre-aggregated data with 24h TTL for real-time analytics.
    """

    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_bounces_hourly": {"config": {"team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED}},
                "web_analytics_stats_table_hourly": {"config": {"team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED}},
            }
        },
    )


# Simple asset checks co-located with the assets
@asset_check(
    asset=web_bounces_hourly,
    name="bounces_hourly_has_data_colocated",
    description="Check if web_bounces_hourly table has data (co-located check)",
)
def bounces_hourly_has_data_colocated() -> AssetCheckResult:
    """
    Simple co-located asset check to verify the web_bounces_hourly table has data.
    """
    try:
        result = sync_execute("SELECT COUNT(*) FROM web_bounces_hourly LIMIT 1")
        row_count = result[0][0] if result and result[0] else 0

        passed = row_count > 0

        return AssetCheckResult(
            passed=passed,
            description=f"Table has {row_count} rows" if passed else "Table is empty",
            metadata={
                "row_count": MetadataValue.int(row_count),
                "table_name": MetadataValue.text("web_bounces_hourly"),
                "co_located": MetadataValue.bool(True),
            },
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking table: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


@asset_check(
    asset=web_stats_hourly,
    name="stats_hourly_has_data_colocated",
    description="Check if web_stats_hourly table has data (co-located check)",
)
def stats_hourly_has_data_colocated() -> AssetCheckResult:
    """
    Simple co-located asset check to verify the web_stats_hourly table has data.
    """
    try:
        result = sync_execute("SELECT COUNT(*) FROM web_stats_hourly LIMIT 1")
        row_count = result[0][0] if result and result[0] else 0

        passed = row_count > 0

        return AssetCheckResult(
            passed=passed,
            description=f"Table has {row_count} rows" if passed else "Table is empty",
            metadata={
                "row_count": MetadataValue.int(row_count),
                "table_name": MetadataValue.text("web_stats_hourly"),
                "co_located": MetadataValue.bool(True),
            },
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking table: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


# Comprehensive web overview accuracy check
@asset_check(
    asset=["web_bounces_hourly", "web_stats_hourly"],
    name="web_overview_accuracy_check",
    description="Validates that pre-aggregated data matches regular WebOverview queries within 1% tolerance",
    blocking=False,
)
def web_overview_accuracy_check() -> AssetCheckResult:
    """
    Comprehensive check: validates pre-aggregated tables match regular WebOverview queries within 1% accuracy.
    """
    from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
    from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers
    from posthog.models import Team
    from dags.web_preaggregated_utils import TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED

    tolerance_pct = 5.0  # 5% tolerance for data quality until we have a clear SLO/SLA
    days_back = 3
    team_ids = TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED[:2]  # Test first 2 teams to avoid overload

    # Test date range
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days_back)
    date_from = start_date.strftime("%Y-%m-%d")
    date_to = end_date.strftime("%Y-%m-%d")

    validation_results = []
    all_teams_valid = True
    failed_teams = []

    for team_id in team_ids:
        try:
            # Check if team exists
            try:
                team = Team.objects.get(id=team_id)
            except Team.DoesNotExist:
                validation_results.append({"team_id": team_id, "error": f"Team {team_id} does not exist"})
                all_teams_valid = False
                failed_teams.append(team_id)
                continue

            # Query with pre-aggregated tables
            query = WebOverviewQuery(
                dateRange=DateRange(date_from=date_from, date_to=date_to),
                properties=[],  # Add empty properties list
            )

            modifiers_pre_agg = HogQLQueryModifiers(
                useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False
            )

            runner_pre_agg = WebOverviewQueryRunner(query=query, team=team, modifiers=modifiers_pre_agg)

            # Query without pre-aggregated tables
            modifiers_regular = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False)

            runner_regular = WebOverviewQueryRunner(query=query, team=team, modifiers=modifiers_regular)

            response_pre_agg = runner_pre_agg.calculate()
            response_regular = runner_regular.calculate()

            # Convert results to dict for comparison
            def results_to_dict(results) -> dict:
                return {item.key: item.value for item in results if item.value is not None}

            pre_agg_metrics = results_to_dict(response_pre_agg.results)
            regular_metrics = results_to_dict(response_regular.results)

            team_validation = {"team_id": team_id, "metrics": {}, "all_within_tolerance": True}

            for metric_key in set(pre_agg_metrics.keys()) | set(regular_metrics.keys()):
                pre_agg_val = pre_agg_metrics.get(metric_key, 0)
                regular_val = regular_metrics.get(metric_key, 0)

                # Calculate percentage difference
                if regular_val == 0 and pre_agg_val == 0:
                    pct_diff = 0.0
                    within_tolerance = True
                elif regular_val == 0:
                    pct_diff = 100.0 if pre_agg_val != 0 else 0.0
                    within_tolerance = pre_agg_val == 0
                else:
                    pct_diff = abs(pre_agg_val - regular_val) / regular_val * 100
                    within_tolerance = pct_diff <= tolerance_pct

                team_validation["metrics"][metric_key] = {
                    "pre_aggregated": pre_agg_val,
                    "regular": regular_val,
                    "pct_difference": pct_diff,
                    "within_tolerance": within_tolerance,
                }

                if not within_tolerance:
                    team_validation["all_within_tolerance"] = False

            validation_results.append(team_validation)

            if not team_validation["all_within_tolerance"]:
                all_teams_valid = False
                failed_teams.append(team_id)

        except Exception as e:
            validation_results.append({"team_id": team_id, "error": str(e)})
            all_teams_valid = False
            failed_teams.append(team_id)

    # Generate summary
    total_metrics = sum(len(result.get("metrics", {})) for result in validation_results)
    failed_metrics = sum(
        1
        for result in validation_results
        for metric in result.get("metrics", {}).values()
        if not metric.get("within_tolerance", True)
    )

    success_rate = (total_metrics - failed_metrics) / max(total_metrics, 1) * 100

    return AssetCheckResult(
        passed=all_teams_valid,
        severity=AssetCheckSeverity.ERROR if not all_teams_valid else None,
        description=f"Accuracy check: {len(team_ids) - len(failed_teams)}/{len(team_ids)} teams passed, {success_rate:.1f}% metrics within {tolerance_pct}% tolerance",
        metadata={
            "success_rate": MetadataValue.float(success_rate),
            "teams_tested": MetadataValue.int(len(team_ids)),
            "teams_passed": MetadataValue.int(len(team_ids) - len(failed_teams)),
            "failed_teams": MetadataValue.json(failed_teams),
            "tolerance_pct": MetadataValue.float(tolerance_pct),
            "date_range": MetadataValue.text(f"{date_from} to {date_to}"),
            "detailed_results": MetadataValue.json(validation_results[:3]),  # Limit for readability
        },
    )
