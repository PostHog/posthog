import time
from datetime import UTC, datetime, timedelta
from typing import Any

import chdb
import dagster
import structlog
from dagster import AssetCheckExecutionContext, AssetCheckResult, AssetCheckSeverity, Field, MetadataValue, asset_check

from posthog.schema import DateRange, HogQLQueryModifiers, WebOverviewItem, WebOverviewQuery

from posthog.hogql.database.schema.web_analytics_s3 import (
    get_s3_function_args,
    get_s3_url,
    get_s3_web_bounces_structure,
    get_s3_web_stats_structure,
)
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.escape import substitute_params
from posthog.clickhouse.query_tagging import DagsterTags, get_query_tags, tags_context
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.models import Team
from posthog.settings.base_variables import DEBUG

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS

logger = structlog.get_logger(__name__)

DEFAULT_TOLERANCE_PCT = 1.0
DEFAULT_DAYS_BACK = 7
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


def table_has_data(
    table_name: str, tags: DagsterTags = None, context: AssetCheckExecutionContext = None
) -> AssetCheckResult:
    # Skip simple data checks during backfill runs if context is provided
    if context and hasattr(context.run, "tags") and context.run.tags and context.run.tags.get("dagster/backfill"):
        return AssetCheckResult(
            passed=True,
            description=f"Skipped {table_name} data check during backfill run",
            metadata={
                "skipped": MetadataValue.bool(True),
                "reason": MetadataValue.text("backfill_optimization"),
                "table_name": MetadataValue.text(table_name),
            },
        )

    try:
        with tags_context(kind="dagster", dagster=tags):
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


def log_query_sql(
    runner, query_name: str, context: AssetCheckExecutionContext, team: Team, use_pre_agg: bool = False
) -> None:
    try:
        if use_pre_agg:
            query_ast = runner.preaggregated_query_builder.get_query()
        else:
            query_ast = runner.to_query()

        executor = HogQLQueryExecutor(query=query_ast, team=team, modifiers=runner.modifiers)
        sql_with_placeholders, sql_context = executor.generate_clickhouse_sql()
        raw_sql = substitute_params(sql_with_placeholders, sql_context.values)
        context.log.info(f"{query_name}:\n {raw_sql}")
    except Exception as e:
        context.log.warning(f"Failed to log {query_name}: {e}")


def setup_accuracy_check_config(
    context: AssetCheckExecutionContext, check_name: str
) -> tuple[float, int, int, str, str]:
    run_config = context.run.run_config.get("ops", {}).get(check_name, {}).get("config", {})
    tolerance_percentage = run_config.get("tolerance_pct", DEFAULT_TOLERANCE_PCT)
    days_back = run_config.get("days_back", DEFAULT_DAYS_BACK)
    team_id = TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS

    end_date = (datetime.now(UTC) - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999).date()
    start_date = end_date - timedelta(days=days_back)
    date_from = start_date.strftime("%Y-%m-%d")
    date_to = end_date.strftime("%Y-%m-%d")

    return tolerance_percentage, days_back, team_id, date_from, date_to


def create_runners_for_accuracy_check(
    team: Team, date_from: str, date_to: str, use_v2_tables: bool = False
) -> tuple[WebOverviewQueryRunner, WebOverviewQueryRunner]:
    query_fn = lambda: WebOverviewQuery(
        dateRange=DateRange(date_from=date_from, date_to=date_to),
        properties=[],
    )

    runner_pre_agg = WebOverviewQueryRunner(
        query=query_fn(),
        team=team,
        use_v2_tables=use_v2_tables,
        modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False),
    )
    runner_regular = WebOverviewQueryRunner(
        query=query_fn(),
        team=team,
        modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=False, convertToProjectTimezone=False),
    )

    return runner_pre_agg, runner_regular


def execute_accuracy_check(
    runner_pre_agg: WebOverviewQueryRunner,
    runner_regular: WebOverviewQueryRunner,
    team_id: int,
    date_from: str,
    date_to: str,
    context: AssetCheckExecutionContext,
    tolerance_percentage: float,
    table_version: str,
) -> tuple[bool, dict[str, Any]]:
    """Execute accuracy check between pre-aggregated and regular query runners."""
    try:
        context.log.info(f"Running {table_version} accuracy check for team {team_id}")

        log_query_sql(
            runner_pre_agg, f"Pre-aggregated SQL ({table_version})", context, runner_pre_agg.team, use_pre_agg=True
        )
        log_query_sql(runner_regular, f"Regular SQL ({table_version})", context, runner_regular.team, use_pre_agg=False)

        context.log.info(f"About to execute pre-aggregated query ({table_version})")
        start_time = time.time()
        pre_agg_response = runner_pre_agg.calculate()
        pre_agg_execution_time = time.time() - start_time

        context.log.info(f"About to execute regular query ({table_version})")
        start_time = time.time()
        regular_response = runner_regular.calculate()
        regular_execution_time = time.time() - start_time

        context.log.info(
            f"Query execution completed for team {team_id} ({table_version}), pre-agg time: {pre_agg_execution_time}, regular time: {regular_execution_time}"
        )

        # Convert results to dict for easier comparison
        def results_to_dict(results: list[WebOverviewItem]) -> dict[str, float]:
            return {item.key: float(item.value) for item in results if item.value is not None}

        pre_agg_metrics = results_to_dict(pre_agg_response.results)
        regular_metrics = results_to_dict(regular_response.results)

        comparison_data = {
            "team_id": team_id,
            "date_from": date_from,
            "date_to": date_to,
            "table_version": table_version,
            "metrics": {},
            "all_within_tolerance": True,
            "tolerance_pct": tolerance_percentage,
            "timing": {"pre_aggregated": pre_agg_execution_time, "regular": regular_execution_time},
        }

        for metric_name in set(pre_agg_metrics.keys()) | set(regular_metrics.keys()):
            pre_agg_value = pre_agg_metrics.get(metric_name, 0)
            regular_value = regular_metrics.get(metric_name, 0)

            # Calculate percentage difference
            if regular_value == 0 and pre_agg_value == 0:
                percentage_difference = 0.0
                within_tolerance = True
            elif regular_value == 0:
                percentage_difference = 100.0 if pre_agg_value != 0 else 0.0
                within_tolerance = pre_agg_value == 0
            else:
                percentage_difference = abs(pre_agg_value - regular_value) / regular_value * 100
                within_tolerance = percentage_difference <= tolerance_percentage

            comparison_data["metrics"][metric_name] = {
                "pre_aggregated": pre_agg_value,
                "regular": regular_value,
                "pct_difference": percentage_difference,
                "within_tolerance": within_tolerance,
            }

            if not within_tolerance:
                comparison_data["all_within_tolerance"] = False

        return comparison_data["all_within_tolerance"], comparison_data

    except Exception as e:
        logger.error(
            f"Error comparing web overview metrics ({table_version})", team_id=team_id, error=str(e), exc_info=True
        )
        return False, {
            "team_id": team_id,
            "error": str(e),
            "date_from": date_from,
            "date_to": date_to,
            "table_version": table_version,
            "metrics": {},
            "all_within_tolerance": False,
            "tolerance_pct": tolerance_percentage,
            "timing": {"pre_aggregated": 0.0, "regular": 0.0},
        }


def create_accuracy_check_result(comparison_data: dict[str, Any], team_id: int, table_version: str) -> AssetCheckResult:
    """Create AssetCheckResult from comparison data with individual metric metadata for Dagster plotting."""
    total_metrics_checked = len(comparison_data.get("metrics", {}))
    failed_metrics = sum(
        1 for metric in comparison_data.get("metrics", {}).values() if not metric.get("within_tolerance", True)
    )

    success_rate = (total_metrics_checked - failed_metrics) / max(total_metrics_checked, 1) * 100

    if success_rate >= 95:
        passed = True
        severity = AssetCheckSeverity.WARN
        description = f"Team {team_id} {table_version} tables passed validation (success rate: {success_rate:.1f}%)"
    else:
        passed = False
        severity = AssetCheckSeverity.ERROR
        description = f"Team {team_id} {table_version} tables failed accuracy validation."

    metadata = {
        "success_rate": MetadataValue.float(success_rate),
        "failed_metrics": MetadataValue.int(failed_metrics),
        "total_metrics": MetadataValue.int(total_metrics_checked),
        "tolerance_percentage": MetadataValue.float(comparison_data.get("tolerance_pct", 0.0)),
        "date_range": MetadataValue.text(f"{comparison_data.get('date_from')} to {comparison_data.get('date_to')}"),
        "table_version": MetadataValue.text(table_version),
        "detailed_results": MetadataValue.json(comparison_data),
    }

    # Add individual metric metadata for Dagster plotting
    metrics = comparison_data.get("metrics", {})
    for metric_name, metric_values in metrics.items():
        metadata.update(
            {
                f"{metric_name}_pre_aggregated": MetadataValue.float(float(metric_values.get("pre_aggregated", 0.0))),
                f"{metric_name}_regular": MetadataValue.float(float(metric_values.get("regular", 0.0))),
                f"{metric_name}_percentage_difference": MetadataValue.float(
                    float(metric_values.get("pct_difference", 0.0))
                ),
                f"{metric_name}_within_tolerance": MetadataValue.bool(metric_values.get("within_tolerance", True)),
            }
        )

    # Add timing metadata if available
    if comparison_data and not comparison_data.get("skipped") and "timing" in comparison_data:
        metadata.update(
            {
                "pre_agg_time": MetadataValue.float(round(comparison_data["timing"]["pre_aggregated"], 3)),
                "regular_time": MetadataValue.float(round(comparison_data["timing"]["regular"], 3)),
            }
        )

    return AssetCheckResult(
        passed=passed,
        severity=severity,
        description=description,
        metadata=metadata,
    )


def run_accuracy_check_for_version(
    context: AssetCheckExecutionContext, check_name: str, table_version: str, use_v2_tables: bool
) -> AssetCheckResult:
    """Generic accuracy check runner for both v1 and v2 tables."""
    # Skip accuracy checks during backfill runs to improve performance
    if hasattr(context.run, "tags") and context.run.tags and context.run.tags.get("dagster/backfill"):
        return AssetCheckResult(
            passed=True,
            description=f"Skipped {table_version} accuracy check during backfill run",
            metadata={
                "skipped": MetadataValue.bool(True),
                "reason": MetadataValue.text("backfill_optimization"),
                "table_version": MetadataValue.text(table_version),
            },
        )

    try:
        tolerance_percentage, days_back, team_id, date_from, date_to = setup_accuracy_check_config(context, check_name)
    except Exception as e:
        context.log.exception(f"Failed to setup accuracy check config: {e}")
        return AssetCheckResult(
            passed=False,
            description=f"Configuration error for {table_version} accuracy check",
            metadata={"error": MetadataValue.text(str(e))},
        )

    get_query_tags().with_dagster(dagster_tags(context))

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        context.log.exception(f"Team {team_id} not found")
        return AssetCheckResult(
            passed=False,
            description=f"Team {team_id} does not exist",
            metadata={"error": MetadataValue.text(f"Team {team_id} not found")},
        )
    except Exception as e:
        context.log.exception(f"Database error while fetching team {team_id}: {e}")
        return AssetCheckResult(
            passed=False,
            description=f"Database error for team {team_id}",
            metadata={"error": MetadataValue.text(str(e))},
        )

    try:
        runner_pre_agg, runner_regular = create_runners_for_accuracy_check(
            team, date_from, date_to, use_v2_tables=use_v2_tables
        )
    except Exception as e:
        context.log.exception(f"Failed to create query runners for {table_version}: {e}")
        return AssetCheckResult(
            passed=False,
            description=f"Query runner creation failed for {table_version}",
            metadata={"error": MetadataValue.text(str(e))},
        )

    try:
        is_valid, comparison_data = execute_accuracy_check(
            runner_pre_agg, runner_regular, team_id, date_from, date_to, context, tolerance_percentage, table_version
        )
        timing = comparison_data.get("timing", {})
        context.log.info(
            f"{table_version.upper()} check - Valid?: {is_valid}. Pre-agg: {timing.get('pre_aggregated', 0):.2f}s, Regular: {timing.get('regular', 0):.2f}s"
        )
    except Exception as e:
        context.log.exception(f"Failed to run {table_version} accuracy check for team {team_id}: {str(e)}")
        comparison_data = {
            "team_id": team_id,
            "error": str(e),
            "date_from": date_from,
            "date_to": date_to,
            "table_version": table_version,
            "skipped": True,
            "tolerance_pct": tolerance_percentage,
            "all_within_tolerance": False,
            "metrics": {},
        }

    return create_accuracy_check_result(comparison_data, team_id, table_version)


@asset_check(
    asset="web_analytics_bounces_daily",
    name="web_analytics_accuracy_check",
    description="Validates that pre-aggregated web analytics data matches regular queries within tolerance",
    blocking=False,
)
def web_analytics_accuracy_check(context: AssetCheckExecutionContext) -> AssetCheckResult:
    """Data quality check: validates v1 pre-aggregated tables match regular WebOverview queries within tolerance."""
    return run_accuracy_check_for_version(context, "web_analytics_accuracy_check", "v1", use_v2_tables=False)


# V2 Table Checks for web_pre_aggregated_* tables
@asset_check(
    asset="web_analytics_team_selection_v2",
    name="web_analytics_team_selection_v2_has_data",
    description="Check if web analytics v2 team selection has teams configured",
)
def web_analytics_team_selection_v2_has_data(context: AssetCheckExecutionContext) -> AssetCheckResult:
    """Verify that v2 team selection has configured teams."""
    # Skip team selection checks during backfill runs
    if hasattr(context.run, "tags") and context.run.tags and context.run.tags.get("dagster/backfill"):
        return AssetCheckResult(
            passed=True,
            description="Skipped team selection check during backfill run",
            metadata={
                "skipped": MetadataValue.bool(True),
                "reason": MetadataValue.text("backfill_optimization"),
            },
        )

    try:
        query = "SELECT COUNT(*) as team_count FROM web_pre_aggregated_teams FINAL WHERE version = (SELECT MAX(version) FROM web_pre_aggregated_teams)"
        result = sync_execute(query)
        team_count = result[0][0] if result and result[0] else 0

        if team_count > 0:
            return AssetCheckResult(
                passed=True,
                description=f"V2 team selection has {team_count} teams configured",
                metadata={"team_count": MetadataValue.int(team_count)},
            )
        else:
            return AssetCheckResult(
                passed=False,
                description="V2 team selection has no teams configured",
                metadata={"team_count": MetadataValue.int(0)},
            )
    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Failed to check v2 team selection: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )


simple_data_checks_job = dagster.define_asset_job(
    name="simple_data_checks_job",
    selection=dagster.AssetSelection.checks_for_assets(
        ["web_analytics_bounces_hourly", "web_analytics_stats_table_hourly"]
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
