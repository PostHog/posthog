import chdb
import structlog
from datetime import datetime, UTC, timedelta
from typing import Any

import dagster
from dagster import (
    Field,
    MetadataValue,
    AssetCheckResult,
    AssetCheckSeverity,
    asset_check,
)
from dags.common import JobOwners
from dags.web_preaggregated_utils import TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS

from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.schema import WebOverviewQuery, DateRange, HogQLQueryModifiers, WebOverviewItem
from posthog.models import Team
from posthog.clickhouse.client import sync_execute
from posthog.settings.base_variables import DEBUG
from posthog.hogql.database.schema.web_analytics_s3 import (
    get_s3_url,
    get_s3_web_stats_structure,
    get_s3_web_bounces_structure,
    get_s3_function_args,
)


logger = structlog.get_logger(__name__)

DEFAULT_TOLERANCE_PCT = 1.0
DEFAULT_DAYS_BACK = 7
DEFAULT_ACCURACY_CHECK_TOLERANCE = 0.5
MAX_TEAMS_PER_BATCH = 10
CHDB_QUERY_TIMEOUT = 60

WEB_DATA_QUALITY_CONFIG_SCHEMA = {
    "tolerance_pct": Field(
        float,
        default_value=DEFAULT_TOLERANCE_PCT,
        description="Tolerance percentage for data accuracy (default 1%)",
    ),
    "days_back": Field(
        int,
        default_value=DEFAULT_DAYS_BACK,
        description="Number of days back to validate data for",
    ),
}


def table_has_data(table_name: str) -> AssetCheckResult:
    try:
        result = sync_execute(f"SELECT COUNT(*) FROM {table_name} LIMIT 1")
        row_count = result[0][0] if result and result[0] else 0

        passed = row_count > 0

        return AssetCheckResult(
            passed=passed,
            description=f"Table has {row_count} rows" if passed else "Table is empty",
            metadata={"row_count": MetadataValue.int(row_count), "table_name": MetadataValue.text(table_name)},
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking table: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


@asset_check(
    asset="web_analytics_bounces_daily",
    name="bounces_daily_has_data",
    description="Check if web_bounces_daily table has data",
)
def bounces_daily_has_data() -> AssetCheckResult:
    return table_has_data("web_bounces_daily")


@asset_check(
    asset="web_analytics_stats_table_daily",
    name="stats_daily_has_data",
    description="Check if web_stats_daily table has data",
)
def stats_daily_has_data() -> AssetCheckResult:
    return table_has_data("web_stats_daily")


@asset_check(
    asset="web_analytics_bounces_hourly",
    name="bounces_hourly_has_data",
    description="Check if web_bounces_hourly table has data",
)
def bounces_hourly_has_data() -> AssetCheckResult:
    return table_has_data("web_bounces_hourly")


@asset_check(
    asset="web_analytics_stats_table_hourly",
    name="stats_hourly_has_data",
    description="Check if web_stats_daily table has data",
)
def stats_hourly_has_data() -> AssetCheckResult:
    return table_has_data("web_stats_hourly")


def check_export_chdb_queryable(export_type: str, log_event_name: str) -> AssetCheckResult:
    try:
        export_filename = f"{export_type}_export"
        export_path = get_s3_url(table_name=export_filename, team_id=TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS)

        if export_type == "web_stats_daily":
            table_structure = get_s3_web_stats_structure().strip()
        elif export_type == "web_bounces_daily":
            table_structure = get_s3_web_bounces_structure().strip()
        else:
            raise ValueError(f"Unknown export type: {export_type}")

        try:
            s3_function_args = get_s3_function_args(export_path)
            s3_query = f"SELECT COUNT(*) as row_count FROM s3({s3_function_args}, '{table_structure}')"
            result = chdb.query(s3_query)
            row_count = int(result.data().strip()) if result.data().strip().isdigit() else 0

            passed = row_count > 0
            env_type = "Minio" if DEBUG else "S3"
            logger.info(log_event_name, export_path=export_path, row_count=row_count, queryable=True, env=env_type)

            return AssetCheckResult(
                passed=passed,
                description=(
                    f"Export file queryable with chdb via {env_type}, contains {row_count} rows"
                    if passed
                    else f"Export file queryable via {env_type} but empty"
                ),
                metadata={
                    "row_count": MetadataValue.int(row_count),
                    "export_path": MetadataValue.text(export_path),
                    "chdb_queryable": MetadataValue.bool(True),
                    "export_type": MetadataValue.text(export_type),
                    "environment": MetadataValue.text(env_type),
                },
            )

        except FileNotFoundError as e:
            # File doesn't exist yet - this is expected for new exports
            error_msg = str(e)
            env_type = "Minio" if DEBUG else "S3"

            logger.info(
                log_event_name, export_path=export_path, status="file_not_found", error=error_msg[:100], env=env_type
            )

            return AssetCheckResult(
                passed=False,
                description=f"Export file not found on {env_type} - may not have been created yet",
                metadata={
                    "export_path": MetadataValue.text(export_path),
                    "error": MetadataValue.text(error_msg),
                    "export_type": MetadataValue.text(export_type),
                    "status": MetadataValue.text("file_not_found"),
                    "environment": MetadataValue.text(env_type),
                },
            )
        except ValueError as e:
            # Handle parsing/format issues
            error_msg = str(e)
            env_type = "Minio" if DEBUG else "S3"

            if "table structure cannot be extracted" in error_msg.lower():
                status = "format_issue"
                description = f"Export file exists on {env_type} but chdb cannot determine structure - this should not happen with explicit structure"
            else:
                status = "parse_error"
                description = f"Error parsing export file on {env_type}: {error_msg}"

            logger.info(log_event_name, export_path=export_path, status=status, error=error_msg[:100], env=env_type)

            return AssetCheckResult(
                passed=False,
                description=description,
                metadata={
                    "export_path": MetadataValue.text(export_path),
                    "error": MetadataValue.text(error_msg[:200]),
                    "export_type": MetadataValue.text(export_type),
                    "status": MetadataValue.text(status),
                    "environment": MetadataValue.text(env_type),
                },
            )
        except Exception as e:
            # Handle other unexpected errors
            error_msg = str(e)
            env_type = "Minio" if DEBUG else "S3"

            # Check for common ClickHouse/S3 errors
            if "CANNOT_STAT" in error_msg or "Cannot stat file" in error_msg:
                status = "file_not_found"
                description = f"Export file not found on {env_type} - may not have been created yet"
            elif "Access denied" in error_msg.lower() or "forbidden" in error_msg.lower():
                status = "access_denied"
                description = f"Access denied to export file on {env_type} - check credentials"
            else:
                status = "other_error"
                description = f"Export file check failed on {env_type}: {error_msg}"

            logger.info(log_event_name, export_path=export_path, status=status, error=error_msg[:100], env=env_type)

            return AssetCheckResult(
                passed=False,
                description=description,
                metadata={
                    "export_path": MetadataValue.text(export_path),
                    "error": MetadataValue.text(error_msg),
                    "export_type": MetadataValue.text(export_type),
                    "status": MetadataValue.text(status),
                    "environment": MetadataValue.text(env_type),
                },
            )

    except ImportError:
        return AssetCheckResult(
            passed=False,
            description="chdb not available - cannot verify export queryability",
            metadata={"error": MetadataValue.text("chdb import failed")},
        )
    except Exception as e:
        logger.exception(f"{log_event_name}_error", error=str(e))
        return AssetCheckResult(
            passed=False,
            description=f"Error checking export with chdb: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )


@asset_check(asset="web_analytics_stats_export", name="stats_export_chdb_queryable")
def stats_export_chdb_queryable() -> AssetCheckResult:
    """
    Check if the web_stats_daily export file can be queried with chdb and contains data.
    """
    return check_export_chdb_queryable("web_stats_daily", "stats_export_chdb_check")


@asset_check(
    asset="web_analytics_bounces_export",
    name="bounces_export_chdb_queryable",
    description="Check if bounces export file can be queried with chdb and has data",
)
def bounces_export_chdb_queryable() -> AssetCheckResult:
    """
    Check if the web_bounces_daily export file can be queried with chdb and contains data.
    """
    return check_export_chdb_queryable("web_bounces_daily", "bounces_export_chdb_check")


def compare_web_overview_metrics(
    team_id: int, date_from: str, date_to: str, tolerance_pct: float = 1.0
) -> tuple[bool, dict[str, Any]]:
    """
    Compare pre-aggregated vs regular WebOverview metrics for accuracy.

    Returns:
        Tuple of (is_within_tolerance, comparison_data)
    """
    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        raise ValueError(f"Team {team_id} does not exist")

    # Query with pre-aggregated tables
    query_pre_agg = WebOverviewQuery(
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        properties=[],  # Add required empty properties field
    )

    modifiers_pre_agg = HogQLQueryModifiers(
        useWebAnalyticsPreAggregatedTables=True,
        convertToProjectTimezone=False,  # Pre-agg tables are in UTC
    )

    runner_pre_agg = WebOverviewQueryRunner(query=query_pre_agg, team=team, modifiers=modifiers_pre_agg)

    # Query without pre-aggregated tables
    # We have an known issue that the buckets are always in UTC, so we need to query in UTC to make sure we're comparing apples to apples
    # This can be improved if we change to hourly buckets but right now this fits our scope
    modifiers_regular = HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False, convertToProjectTimezone=False)

    runner_regular = WebOverviewQueryRunner(query=query_pre_agg, team=team, modifiers=modifiers_regular)

    try:
        response_pre_agg = runner_pre_agg.calculate()
        response_regular = runner_regular.calculate()

        # Convert results to dict for easier comparison
        def results_to_dict(results: list[WebOverviewItem]) -> dict[str, float]:
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
            "tolerance_pct": tolerance_pct,
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
                "within_tolerance": within_tolerance,
            }

            if not within_tolerance:
                comparison_data["all_within_tolerance"] = False

        return comparison_data["all_within_tolerance"], comparison_data

    except Exception as e:
        logger.error("Error comparing web overview metrics", team_id=team_id, error=str(e), exc_info=True)
        return False, {"team_id": team_id, "error": str(e), "date_from": date_from, "date_to": date_to}


@asset_check(
    asset="web_analytics_combined_views",
    name="web_analytics_accuracy_check",
    description="Validates that pre-aggregated web analytics data matches regular queries within tolerance",
    blocking=False,  # Don't block asset materialization if check fails
)
def web_analytics_accuracy_check(context: dagster.AssetCheckExecutionContext) -> AssetCheckResult:
    """
    Data quality check: validates pre-aggregated tables match regular WebOverview queries within some % accuracy.
    """
    run_config = context.run.run_config.get("ops", {}).get("web_analytics_accuracy_check", {}).get("config", {})
    tolerance_pct = run_config.get("tolerance_pct", DEFAULT_TOLERANCE_PCT)
    days_back = run_config.get("days_back", DEFAULT_DAYS_BACK)
    team_id = TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS

    end_date = (datetime.now(UTC) - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999).date()
    start_date = end_date - timedelta(days=days_back)
    date_from = start_date.strftime("%Y-%m-%d")
    date_to = end_date.strftime("%Y-%m-%d")

    validation_results = []

    context.log.info(f"Starting accuracy validation for team {team_id}, tolerance: {tolerance_pct}%")

    try:
        is_valid, comparison_data = compare_web_overview_metrics(
            team_id=team_id, date_from=date_from, date_to=date_to, tolerance_pct=tolerance_pct
        )

        validation_results.append(comparison_data)

        context.log.info(f"Comparison is valid: {is_valid}, comparison data: {comparison_data}")
    except Exception as e:
        context.log.exception(f"Failed to validate team {team_id}: {str(e)}")
        validation_results.append(
            {"team_id": team_id, "error": str(e), "date_from": date_from, "date_to": date_to, "skipped": True}
        )

    total_metrics_checked = sum(
        len(result.get("metrics", {})) for result in validation_results if not result.get("skipped")
    )
    failed_metrics = sum(
        1
        for result in validation_results
        if not result.get("skipped")
        for metric in result.get("metrics", {}).values()
        if not metric.get("within_tolerance", True)
    )

    success_rate = (total_metrics_checked - failed_metrics) / max(total_metrics_checked, 1) * 100

    if success_rate >= 95:
        passed = True
        severity = AssetCheckSeverity.WARN
        description = f"Team {team_id} passed validation (success rate: {success_rate:.1f}%)"
    else:
        passed = False
        severity = AssetCheckSeverity.ERROR
        description = f"Team {team_id} failed accuracy validation."

    return AssetCheckResult(
        passed=passed,
        severity=severity,
        description=description,
        metadata={
            "success_rate": MetadataValue.float(success_rate),
            "failed_metrics": MetadataValue.int(failed_metrics),
            "total_metrics": MetadataValue.int(total_metrics_checked),
            "tolerance_pct": MetadataValue.float(tolerance_pct),
            "date_range": MetadataValue.text(f"{date_from} to {date_to}"),
            "detailed_results": MetadataValue.json(validation_results),
        },
    )


web_analytics_data_quality_job = dagster.define_asset_job(
    name="web_analytics_data_quality_job",
    selection=dagster.AssetSelection.checks_for_assets(
        [
            "web_analytics_bounces_hourly",
            "web_analytics_stats_table_hourly",
            "web_analytics_bounces_daily",
            "web_analytics_stats_table_daily",
        ]
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="0 2 * * 0",
    job=web_analytics_data_quality_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_weekly_data_quality_schedule(context: dagster.ScheduleEvaluationContext):
    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_accuracy_check": {
                    "config": {
                        "tolerance_pct": DEFAULT_ACCURACY_CHECK_TOLERANCE,
                        "days_back": DEFAULT_DAYS_BACK,
                    }
                }
            }
        },
        tags={"trigger": "weekly_schedule"},
    )


simple_data_checks_job = dagster.define_asset_job(
    name="simple_data_checks_job",
    selection=dagster.AssetSelection.checks_for_assets(
        ["web_analytics_bounces_hourly", "web_analytics_stats_table_hourly"]
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
