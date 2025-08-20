from datetime import UTC, datetime, timedelta
import os

import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition
from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from dags.web_preaggregated_team_selection import get_team_ids_from_sources

# Configuration
BACKFILL_LOOKBACK_DAYS_ENV_VAR = "WEB_ANALYTICS_BACKFILL_LOOKBACK_DAYS"
DEFAULT_BACKFILL_LOOKBACK_DAYS = 30
MAX_BACKFILL_PARTITIONS_PER_RUN_ENV_VAR = "WEB_ANALYTICS_BACKFILL_MAX_PARTITIONS_PER_RUN"
DEFAULT_MAX_BACKFILL_PARTITIONS = 7

backfill_lookback_days = int(os.getenv(BACKFILL_LOOKBACK_DAYS_ENV_VAR, DEFAULT_BACKFILL_LOOKBACK_DAYS))
max_backfill_partitions_per_run = int(
    os.getenv(MAX_BACKFILL_PARTITIONS_PER_RUN_ENV_VAR, DEFAULT_MAX_BACKFILL_PARTITIONS)
)

backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_backfill_partitions_per_run)
partition_def = DailyPartitionsDefinition(start_date="2024-01-01")


def get_teams_missing_data(
    context: dagster.OpExecutionContext,
    cluster: ClickhouseCluster,
    lookback_days: int = backfill_lookback_days,
) -> dict[str, set[str]]:
    """
    Identify teams that have missing data in pre-aggregated tables using direct queries.

    Returns:
        Dict mapping table names to sets of missing partition dates for teams
    """
    context.log.info(f"Checking for missing data in last {lookback_days} days")

    # Get currently enabled teams
    enabled_teams = get_team_ids_from_sources(context)
    if not enabled_teams:
        context.log.info("No enabled teams found")
        return {}

    enabled_teams_str = ",".join(str(team_id) for team_id in enabled_teams)
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=lookback_days)

    tables_to_check = ["web_pre_aggregated_stats", "web_pre_aggregated_bounces"]
    missing_data = {}

    for table_name in tables_to_check:
        context.log.info(f"Checking {table_name} for missing data")

        # Query to find missing partitions for enabled teams
        query = f"""
        WITH
            enabled_teams AS (
                SELECT team_id
                FROM (SELECT {enabled_teams_str} as team_id)
                ARRAY JOIN [team_id] AS team_id
            ),
            date_range AS (
                SELECT toDate('{start_date}') + number AS partition_date
                FROM numbers(dateDiff('day', toDate('{start_date}'), toDate('{end_date}')) + 1)
            ),
            expected_partitions AS (
                SELECT
                    et.team_id,
                    dr.partition_date,
                    formatDateTime(dr.partition_date, '%Y%m%d') AS partition_id
                FROM enabled_teams et
                CROSS JOIN date_range dr
            ),
            existing_partitions AS (
                SELECT DISTINCT
                    team_id,
                    toDate(period_bucket) AS partition_date,
                    formatDateTime(toDate(period_bucket), '%Y%m%d') AS partition_id
                FROM {table_name}
                WHERE toDate(period_bucket) >= toDate('{start_date}')
                  AND toDate(period_bucket) <= toDate('{end_date}')
                  AND team_id IN ({enabled_teams_str})
            )
        SELECT
            ep.team_id,
            ep.partition_date,
            ep.partition_id
        FROM expected_partitions ep
        LEFT JOIN existing_partitions exp ON (
            ep.team_id = exp.team_id
            AND ep.partition_date = exp.partition_date
        )
        WHERE exp.team_id IS NULL
        ORDER BY ep.team_id, ep.partition_date
        """

        try:
            result = sync_execute(query)
            missing_partitions = set()

            for _team_id, partition_date, _partition_id in result:
                missing_partitions.add(partition_date.strftime("%Y-%m-%d"))

            if missing_partitions:
                missing_data[table_name] = missing_partitions
                context.log.info(f"Found {len(missing_partitions)} missing partitions in {table_name}")
            else:
                context.log.info(f"No missing partitions found in {table_name}")

        except Exception as e:
            context.log.warning(f"Error checking missing data for {table_name}: {e}")

    return missing_data


def should_run_backfill(context: dagster.OpExecutionContext, missing_data: dict[str, set[str]]) -> bool:
    """
    Determine if backfill should run based on missing data.

    Implements 80/20 rule: only run if there's meaningful missing data.
    """
    total_missing = sum(len(partitions) for partitions in missing_data.values())

    # Don't run for very small amounts of missing data (less than 3 partitions total)
    if total_missing < 3:
        context.log.info(f"Only {total_missing} missing partitions found, skipping backfill")
        return False

    context.log.info(f"Found {total_missing} missing partitions across tables, proceeding with backfill")
    return True


@dagster.asset(
    name="web_analytics_backfill_detector",
    group_name="web_analytics_backfill",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_backfill_detector(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Detects teams with missing web analytics pre-aggregated data and determines
    if backfill is needed.
    """
    context.log.info("Starting backfill detection")

    missing_data = get_teams_missing_data(context, cluster)
    should_backfill = should_run_backfill(context, missing_data)

    total_missing = sum(len(partitions) for partitions in missing_data.values())
    tables_affected = list(missing_data.keys())

    metadata = {
        "should_backfill": should_backfill,
        "total_missing_partitions": total_missing,
        "tables_affected": str(tables_affected),
        "lookback_days": backfill_lookback_days,
    }

    if missing_data:
        for table, partitions in missing_data.items():
            metadata[f"{table}_missing_count"] = len(partitions)
            metadata[f"{table}_sample_dates"] = str(sorted(partitions)[:5])

    context.log.info(f"Backfill detection complete: should_backfill={should_backfill}")

    return dagster.MaterializeResult(metadata=metadata)


# Dagster Ops for manual operations
@dagster.op(
    name="check_missing_data",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def check_missing_data_op(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """
    Op to check for missing data and return detailed results.
    Run with: dagster job execute -j check_missing_data_job
    """
    context.log.info("Checking for missing web analytics data")

    missing_data = get_teams_missing_data(context, cluster)
    total_missing = sum(len(partitions) for partitions in missing_data.values())

    results = {
        "total_missing_partitions": total_missing,
        "tables_with_missing_data": len(missing_data),
        "should_run_backfill": should_run_backfill(context, missing_data),
        "lookback_days": backfill_lookback_days,
        "details": {},
    }

    for table_name, missing_partitions in missing_data.items():
        results["details"][table_name] = {
            "missing_count": len(missing_partitions),
            "sample_dates": sorted(missing_partitions)[:10],  # Show first 10
        }

        context.log.info(
            f"Table {table_name}: {len(missing_partitions)} missing partitions. "
            f"Sample: {sorted(missing_partitions)[:5]}"
        )

    if total_missing == 0:
        context.log.info("✅ No missing data found!")
    else:
        context.log.info(f"📊 Found {total_missing} missing partitions across {len(missing_data)} tables")

    return results


@dagster.op(
    name="show_data_gaps_detailed",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config_schema={"days_back": dagster.Field(int, default_value=7)},
)
def show_data_gaps_detailed_op(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """
    Op to show detailed data gaps for debugging.
    Run with: dagster job execute -j show_data_gaps_job -c '{"days_back": 14}'
    """
    days_back = context.op_config["days_back"]
    context.log.info(f"Showing detailed data gaps for last {days_back} days")

    missing_data = get_teams_missing_data(context, cluster, days_back)

    detailed_gaps = {}

    for table_name, missing_partitions in missing_data.items():
        context.log.info(f"\n--- Analyzing {table_name} ---")

        if not missing_partitions:
            context.log.info("  ✅ No missing data found")
            detailed_gaps[table_name] = {"missing_count": 0, "missing_dates": []}
            continue

        sorted_dates = sorted(missing_partitions)

        # Group consecutive dates for better readability
        date_ranges = []
        if sorted_dates:
            start = end = sorted_dates[0]

            for i in range(1, len(sorted_dates)):
                current = sorted_dates[i]
                if (
                    datetime.strptime(current, "%Y-%m-%d").date() - datetime.strptime(end, "%Y-%m-%d").date()
                ).days == 1:
                    end = current
                else:
                    date_ranges.append(f"{start}" if start == end else f"{start} to {end}")
                    start = end = current

            date_ranges.append(f"{start}" if start == end else f"{start} to {end}")

        detailed_gaps[table_name] = {
            "missing_count": len(missing_partitions),
            "missing_dates": sorted_dates[:20],  # Show first 20
            "date_ranges": date_ranges,
        }

        context.log.info(f"  📊 {len(missing_partitions)} missing dates: {', '.join(date_ranges)}")

    return detailed_gaps


def get_partition_requests_for_missing_data(
    context: dagster.OpExecutionContext, missing_data: dict[str, set[str]]
) -> list[dagster.RunRequest]:
    """
    Generate partition-based run requests for missing data.
    """
    # Get all unique missing dates across tables
    all_missing_dates = set()
    for partitions in missing_data.values():
        all_missing_dates.update(partitions)

    # Sort dates and limit to max partitions per run
    sorted_dates = sorted(all_missing_dates)
    limited_dates = sorted_dates[:max_backfill_partitions_per_run]

    if len(sorted_dates) > max_backfill_partitions_per_run:
        context.log.info(
            f"Limiting backfill to {max_backfill_partitions_per_run} partitions " f"out of {len(sorted_dates)} missing"
        )

    run_requests = []
    for partition_date in limited_dates:
        run_requests.append(
            dagster.RunRequest(
                partition_key=partition_date,
                tags={
                    "backfill_run": "true",
                    "missing_data_detected": "true",
                },
            )
        )

    return run_requests


@dagster.sensor(
    name="web_analytics_backfill_sensor",
    asset_selection=["web_pre_aggregated_bounces", "web_pre_aggregated_stats"],
    minimum_interval_seconds=3600 * 6,  # Run every 6 hours
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    default_status=dagster.DefaultSensorStatus.STOPPED,  # Start in stopped state for safety
)
def web_analytics_backfill_sensor(context: dagster.SensorEvaluationContext):
    """
    Sensor that triggers backfill when missing data is detected.

    SAFETY: This sensor starts in STOPPED state by default.
    Manually start it in Dagster UI when ready for production use.
    """
    from posthog.clickhouse.cluster import ClickhouseCluster

    # Get cluster resource (this is a simplified approach - in practice you'd get this from context)
    cluster = ClickhouseCluster()

    # Check for missing data
    missing_data = get_teams_missing_data(context, cluster)

    if not should_run_backfill(context, missing_data):
        context.log.info("No backfill needed at this time")
        return dagster.SkipReason("No significant missing data detected")

    # Generate run requests for missing partitions
    run_requests = get_partition_requests_for_missing_data(context, missing_data)

    context.log.info(f"Would trigger backfill for {len(run_requests)} partitions")
    partitions = [req.partition_key for req in run_requests]
    context.log.info(f"Partitions that would be backfilled: {partitions}")

    # TODO: Remove this comment to enable actual backfill
    # return run_requests
    return dagster.SkipReason(f"Backfill disabled - would process {len(run_requests)} partitions: {partitions}")


@dagster.schedule(
    cron_schedule="0 2 * * *",  # Run daily at 2 AM UTC
    job_name="web_pre_aggregate_job",
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "backfill_schedule": "true"},
    default_status=dagster.DefaultScheduleStatus.STOPPED,  # Start in stopped state for safety
)
def web_analytics_backfill_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Daily schedule that checks for and triggers backfill of missing data.
    Only runs if there are teams with missing data periods.

    SAFETY: This schedule starts in STOPPED state by default.
    Manually start it in Dagster UI when ready for production use.
    """
    from posthog.clickhouse.cluster import ClickhouseCluster

    cluster = ClickhouseCluster()

    # Check for missing data
    missing_data = get_teams_missing_data(context, cluster)

    if not should_run_backfill(context, missing_data):
        context.log.info("No backfill needed, skipping scheduled run")
        return dagster.SkipReason("No significant missing data detected")

    # Generate run requests for missing partitions
    run_requests = get_partition_requests_for_missing_data(context, missing_data)

    context.log.info(f"Would schedule backfill for {len(run_requests)} partitions")
    partitions = [req.partition_key for req in run_requests]
    context.log.info(f"Partitions that would be backfilled: {partitions}")

    # TODO: Remove this comment to enable actual backfill
    # Return the first run request (Dagster schedules return single requests)
    # if run_requests:
    #     return run_requests[0]

    return dagster.SkipReason(f"Backfill disabled - would process {len(run_requests)} partitions: {partitions}")


# Dagster Jobs for CLI execution
@dagster.job(
    name="check_missing_data_job",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "type": "diagnostic"},
)
def check_missing_data_job():
    """
    Job to check for missing data.
    Run with: dagster job execute -j check_missing_data_job
    """
    check_missing_data_op()


@dagster.job(
    name="show_data_gaps_job",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "type": "diagnostic"},
    config=dagster.ConfigMapping(
        config_schema={"days_back": dagster.Field(int, default_value=7)},
        config_fn=lambda cfg: {"ops": {"show_data_gaps_detailed": {"config": {"days_back": cfg["days_back"]}}}},
    ),
)
def show_data_gaps_job():
    """
    Job to show detailed data gaps.
    Run with: dagster job execute -j show_data_gaps_job
    Run with custom days: dagster job execute -j show_data_gaps_job -c '{"days_back": 14}'
    """
    show_data_gaps_detailed_op()
