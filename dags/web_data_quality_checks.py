from datetime import datetime, UTC, timedelta
from typing import Dict, Any, List, Tuple
import structlog

import dagster
from dagster import Field, MetadataValue, AssetCheckResult, AssetCheckSeverity, asset_check, sensor, AssetMaterialization, RunRequest
from dags.common import JobOwners
from dags.web_preaggregated_utils import TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers, WebOverviewItem
from posthog.models import Team
from posthog.clickhouse.client import sync_execute

logger = structlog.get_logger(__name__)

WEB_DATA_QUALITY_CONFIG_SCHEMA = {
    "team_ids": Field(
        list,
        default_value=TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
        description="List of team IDs to validate data quality for",
    ),
    "tolerance_pct": Field(
        float,
        default_value=1.0,
        description="Tolerance percentage for data accuracy (default 1%)",
    ),
    "days_back": Field(
        int,
        default_value=7,
        description="Number of days back to validate data for",
    ),
}


# Simple asset check to debug - just check if table has data
@asset_check(
    asset="web_analytics_bounces_hourly",
    name="bounces_hourly_has_data",
    description="Simple check: verify the bounces hourly table has data",
)
def bounces_hourly_has_data() -> AssetCheckResult:
    """
    Simple asset check to verify the web_bounces_hourly table has data.
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
                "table_name": MetadataValue.text("web_bounces_hourly")
            }
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error checking table: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))}
        )


# Another simple check for stats table
@asset_check(
    asset="web_analytics_stats_table_hourly", 
    name="stats_hourly_has_data",
    description="Simple check: verify the stats hourly table has data",
)
def stats_hourly_has_data() -> AssetCheckResult:
    """
    Simple asset check to verify the web_stats_hourly table has data.
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
                "table_name": MetadataValue.text("web_stats_hourly")
            }
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Error checking table: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))}
        )


def compare_web_overview_metrics(
    team_id: int,
    date_from: str,
    date_to: str,
    tolerance_pct: float = 1.0
) -> Tuple[bool, Dict[str, Any]]:
    """
    Compare pre-aggregated vs regular WebOverview metrics for accuracy.
    
    Returns:
        Tuple of (is_within_tolerance, comparison_data)
    """
    team = Team.objects.get(id=team_id)
    
    # Query with pre-aggregated tables
    query_pre_agg = WebOverviewQuery(
        dateRange=DateRange(
            date_from=date_from,
            date_to=date_to
        )
    )
    
    modifiers_pre_agg = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=True,
        convertToProjectTimezone=False  # Pre-agg tables are in UTC
    )
    
    runner_pre_agg = WebOverviewQueryRunner(
        query=query_pre_agg,
        team=team,
        modifiers=modifiers_pre_agg
    )
    
    # Query without pre-aggregated tables
    modifiers_regular = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=False
    )
    
    runner_regular = WebOverviewQueryRunner(
        query=query_pre_agg,
        team=team,
        modifiers=modifiers_regular
    )
    
    try:
        response_pre_agg = runner_pre_agg.calculate()
        response_regular = runner_regular.calculate()
        
        # Convert results to dict for easier comparison
        def results_to_dict(results: List[WebOverviewItem]) -> Dict[str, float]:
            return {item.key: item.value for item in results if item.value is not None}
        
        pre_agg_metrics = results_to_dict(response_pre_agg.results)
        regular_metrics = results_to_dict(response_regular.results)
        
        comparison_data = {
            "team_id": team_id,
            "date_from": date_from,
            "date_to": date_to,
            "pre_aggregated_used": response_pre_agg.usedPreAggregatedTables,
            "metrics": {},
            "all_within_tolerance": True,
            "tolerance_pct": tolerance_pct
        }
        
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
            
            comparison_data["metrics"][metric_key] = {
                "pre_aggregated": pre_agg_val,
                "regular": regular_val,
                "pct_difference": pct_diff,
                "within_tolerance": within_tolerance
            }
            
            if not within_tolerance:
                comparison_data["all_within_tolerance"] = False
        
        return comparison_data["all_within_tolerance"], comparison_data
        
    except Exception as e:
        logger.exception("Error comparing web overview metrics", team_id=team_id, error=str(e))
        return False, {
            "team_id": team_id,
            "error": str(e),
            "date_from": date_from,
            "date_to": date_to
        }


@asset_check(
    asset=["web_analytics_bounces_hourly", "web_analytics_stats_table_hourly", "web_analytics_bounces_daily", "web_analytics_stats_table_daily"],
    name="web_analytics_accuracy_check",
    description="Validates that pre-aggregated web analytics data matches regular queries within tolerance",
    blocking=False,  # Don't block asset materialization if check fails
)
def web_analytics_accuracy_check(context: dagster.AssetCheckExecutionContext) -> AssetCheckResult:
    """
    Data quality check: validates pre-aggregated tables match regular WebOverview queries within 1% accuracy.
    """
    # Throttling: Skip if run recently (unless forced via config)
    from dagster import SkipReason
    
    # Check if we should skip this run to avoid CH overload
    last_run_time = context.instance.get_latest_materialization_event(
        dagster.AssetKey(["web_analytics_accuracy_check"])
    )
    
    if last_run_time:
        hours_since_last_run = (datetime.now(UTC) - last_run_time.timestamp).total_seconds() / 3600
        min_hours_between_runs = 4  # Default: minimum 4 hours between runs
        
        # Get config from run config or use defaults
        run_config = context.run.run_config.get("ops", {}).get("web_analytics_accuracy_check", {}).get("config", {})
        
        # Allow override via config
        force_run = run_config.get("force_run", False)
        min_hours_between_runs = run_config.get("min_hours_between_runs", min_hours_between_runs)
        
        if hours_since_last_run < min_hours_between_runs and not force_run:
            return AssetCheckResult(
                passed=True,
                description=f"Skipped - last run was {hours_since_last_run:.1f} hours ago (minimum: {min_hours_between_runs}h). Use force_run=true to override.",
                metadata={"skipped": MetadataValue.bool(True), "hours_since_last_run": MetadataValue.float(hours_since_last_run)}
            )
    
    run_config = context.run.run_config.get("ops", {}).get("web_analytics_accuracy_check", {}).get("config", {})
    team_ids = run_config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    tolerance_pct = run_config.get("tolerance_pct", 1.0)
    days_back = run_config.get("days_back", 7)
    
    # Test the last N days
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=days_back)
    date_from = start_date.strftime("%Y-%m-%d")
    date_to = end_date.strftime("%Y-%m-%d")
    
    validation_results = []
    all_teams_valid = True
    failed_teams = []
    
    for team_id in team_ids:
        context.log.info(f"Validating data quality for team {team_id}")
        
        is_valid, comparison_data = compare_web_overview_metrics(
            team_id=team_id,
            date_from=date_from,
            date_to=date_to,
            tolerance_pct=tolerance_pct
        )
        
        validation_results.append(comparison_data)
        
        if not is_valid:
            all_teams_valid = False
            failed_teams.append(team_id)
            
            # Log specific metric failures
            if "metrics" in comparison_data:
                for metric_key, metric_data in comparison_data["metrics"].items():
                    if not metric_data.get("within_tolerance", True):
                        context.log.error(
                            "Metric accuracy check failed",
                            team_id=team_id,
                            metric=metric_key,
                            pre_aggregated_value=metric_data.get("pre_aggregated"),
                            regular_value=metric_data.get("regular"),
                            pct_difference=metric_data.get("pct_difference"),
                            tolerance_pct=tolerance_pct
                        )
    
    # Generate summary statistics
    total_metrics_checked = sum(len(result.get("metrics", {})) for result in validation_results)
    failed_metrics = sum(
        1 for result in validation_results 
        for metric in result.get("metrics", {}).values() 
        if not metric.get("within_tolerance", True)
    )
    
    success_rate = (total_metrics_checked - failed_metrics) / max(total_metrics_checked, 1) * 100
    
    # Determine check result
    if all_teams_valid:
        severity = AssetCheckSeverity.WARN if success_rate < 100 else None
        passed = True
        description = f"All {len(team_ids)} teams passed accuracy validation within {tolerance_pct}% tolerance"
    else:
        severity = AssetCheckSeverity.ERROR
        passed = False
        description = f"{len(failed_teams)} of {len(team_ids)} teams failed accuracy validation. Failed teams: {failed_teams}"
    
    context.log.info(
        "Data quality validation completed",
        success_rate=success_rate,
        teams_passed=len(team_ids) - len(failed_teams),
        total_teams=len(team_ids),
        failed_teams=failed_teams
    )
    
    return AssetCheckResult(
        passed=passed,
        severity=severity,
        description=description,
        metadata={
            "success_rate": MetadataValue.float(success_rate),
            "teams_passed": MetadataValue.int(len(team_ids) - len(failed_teams)),
            "total_teams": MetadataValue.int(len(team_ids)),
            "failed_metrics": MetadataValue.int(failed_metrics),
            "total_metrics": MetadataValue.int(total_metrics_checked),
            "tolerance_pct": MetadataValue.float(tolerance_pct),
            "date_range": MetadataValue.text(f"{date_from} to {date_to}"),
            "failed_teams": MetadataValue.json(failed_teams),
            "detailed_results": MetadataValue.json(validation_results)
        }
    )


# Job to run data quality checks
web_analytics_data_quality_job = dagster.define_asset_job(
    name="web_analytics_data_quality_job",
    selection=dagster.AssetSelection.checks_for_assets([
        "web_analytics_bounces_hourly", 
        "web_analytics_stats_table_hourly",
        "web_analytics_bounces_daily", 
        "web_analytics_stats_table_daily"
    ]),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@sensor(
    asset_selection=[
        dagster.AssetKey("web_analytics_bounces_daily"),
        dagster.AssetKey("web_analytics_stats_table_daily"), 
        dagster.AssetKey("web_analytics_bounces_hourly"),
        dagster.AssetKey("web_analytics_stats_table_hourly"),
    ],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_data_quality_sensor(context: dagster.SensorEvaluationContext):
    """
    Triggers data quality checks after daily or hourly pre-aggregated tables are materialized.
    Includes smart throttling to avoid ClickHouse overload.
    """
    # Since this sensor triggers on any asset materialization from our selection,
    # we'll run a comprehensive check with throttling to avoid overload
    
    context.log.info("Web analytics asset materialized, triggering data quality check")
    
    return [
        RunRequest(
            run_key=f"quality_check_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
            job_name="web_analytics_data_quality_job",
            run_config={
                "ops": {
                    "web_analytics_accuracy_check": {
                        "config": {
                            "team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
                            "tolerance_pct": 1.0,
                            "days_back": 3,  # Check last 3 days
                            "min_hours_between_runs": 4,  # Throttle to max every 4 hours
                            "force_run": False
                        }
                    }
                }
            },
            tags={"trigger": "asset_materialization"}
        )
    ]


# Optional: Keep the manual schedule for off-peak comprehensive checks
@dagster.schedule(
    cron_schedule="0 2 * * 0",  # Weekly on Sunday at 2 AM UTC
    job=web_analytics_data_quality_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_weekly_data_quality_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Weekly comprehensive data quality validation (off-peak, manual override).
    """
    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_accuracy_check": {
                    "config": {
                        "team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
                        "tolerance_pct": 0.5,  # Strict weekly check
                        "days_back": 14,  # Check 2 weeks of data
                        "force_run": True,  # Override throttling for weekly check
                        "min_hours_between_runs": 1
                    }
                }
            }
        },
        tags={"trigger": "weekly_schedule"}
    )


# Simple job for debugging - just the basic checks
simple_data_checks_job = dagster.define_asset_job(
    name="simple_data_checks_job",
    selection=dagster.AssetSelection.checks_for_assets([
        "web_analytics_bounces_hourly",
        "web_analytics_stats_table_hourly"
    ]),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
) 