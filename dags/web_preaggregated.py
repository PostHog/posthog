import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.sql import WEB_BOUNCES_INSERT_SQL, WEB_STATS_INSERT_SQL
from posthog.models.web_preaggregated.team_selection_strategies import get_teams_with_missing_data

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    DAGSTER_WEB_JOB_TIMEOUT,
    HISTORICAL_DAILY_CRON_SCHEDULE,
    INTRA_DAY_HOURLY_CRON_SCHEDULE,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
    check_for_concurrent_runs,
    clear_all_staging_partitions,
    drop_partitions_for_date_range,
    merge_clickhouse_settings,
    swap_partitions_from_staging,
    web_analytics_retry_policy_def,
)

MAX_PARTITIONS_PER_RUN_ENV_VAR = "DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN"
max_partitions_per_run = int(os.getenv(MAX_PARTITIONS_PER_RUN_ENV_VAR, 1))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)
partition_def = DailyPartitionsDefinition(start_date="2024-01-01", end_offset=1)

# Backfill configuration constants
BACKFILL_LOOKBACK_DAYS = int(os.getenv("WEB_ANALYTICS_BACKFILL_LOOKBACK_DAYS", "7"))
BACKFILL_HISTORICAL_DAYS = int(os.getenv("WEB_ANALYTICS_BACKFILL_HISTORICAL_DAYS", "30"))
BACKFILL_MAX_PARTITIONS_PER_RUN = int(os.getenv("WEB_ANALYTICS_BACKFILL_MAX_PARTITIONS_PER_RUN", "5"))
BACKFILL_MAX_CONCURRENT = int(os.getenv("WEB_ANALYTICS_BACKFILL_MAX_CONCURRENT", "2"))


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    cluster: ClickhouseCluster,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids")
    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(f"Getting ready to pre-aggregate {table_name} for {context.partition_time_window}")

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    staging_table_name = f"{table_name}_staging"

    try:
        # 1. Clean staging table partitions for the date range
        context.log.info(f"Cleaning staging partitions for {date_start} to {date_end}")
        drop_partitions_for_date_range(context, cluster, staging_table_name, date_start, date_end)

        # 2. Generate hourly data into staging table
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids,
            settings=ch_settings,
            table_name=staging_table_name,
            granularity="hourly",
        )

        context.log.info(f"Populating staging table with hourly data from {date_start} to {date_end}")
        context.log.info(insert_query)
        sync_execute(insert_query)

        # 3. Atomically swap partitions from staging to target
        context.log.info(f"Swapping partitions from {staging_table_name} to {table_name}")
        swap_partitions_from_staging(context, cluster, table_name, staging_table_name)

        # 4. Clean up staging partitions to speed up next run
        context.log.info(f"Cleaning up staging partitions")
        drop_partitions_for_date_range(context, cluster, staging_table_name, date_start, date_end)

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate data {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_pre_aggregated_bounces",
    group_name="web_analytics_v2",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_team_selection_v2"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_pre_aggregated_bounces"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_pre_aggregated_bounces(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_pre_aggregated_bounces",
        sql_generator=WEB_BOUNCES_INSERT_SQL,
        cluster=cluster,
    )


@dagster.asset(
    name="web_pre_aggregated_stats",
    group_name="web_analytics_v2",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_team_selection_v2"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_pre_aggregated_stats"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_pre_aggregated_stats(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_pre_aggregated_stats",
        sql_generator=WEB_STATS_INSERT_SQL,
        cluster=cluster,
    )


@dagster.asset(
    name="clear_web_staging_partitions",
    group_name="web_analytics_v2",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def clear_web_staging_partitions(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Utility asset to clear all partitions from staging tables.
    Use this to clean up accumulated historical data in staging tables.
    Ideally, this should not be required, but can be useful for debugging the changes we're doing
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))

    staging_tables = ["web_pre_aggregated_stats_staging", "web_pre_aggregated_bounces_staging"]

    for staging_table in staging_tables:
        context.log.info(f"Clearing all partitions from {staging_table}")
        clear_all_staging_partitions(context, cluster, staging_table)

    context.log.info("Finished clearing all staging partitions")


web_pre_aggregate_job = dagster.define_asset_job(
    name="web_pre_aggregate_job",
    selection=["web_pre_aggregated_bounces", "web_pre_aggregated_stats"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(DAGSTER_WEB_JOB_TIMEOUT),
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 1}),
)


@dagster.schedule(
    cron_schedule=HISTORICAL_DAILY_CRON_SCHEDULE,
    job=web_pre_aggregate_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_historical_schedule(context: dagster.ScheduleEvaluationContext):
    # Check for existing runs of the same job to prevent concurrent execution
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    return dagster.RunRequest(
        partition_key=yesterday,
    )


@dagster.schedule(
    cron_schedule=INTRA_DAY_HOURLY_CRON_SCHEDULE,
    job=web_pre_aggregate_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_current_day_schedule(context: dagster.ScheduleEvaluationContext):
    # Check for existing runs of the same job to prevent concurrent execution
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    return dagster.RunRequest(
        partition_key=datetime.now(UTC).strftime("%Y-%m-%d"),
    )


# Backfill Assets and Schedules
backfill_partition_def = DailyPartitionsDefinition(start_date="2024-01-01", end_offset=-BACKFILL_HISTORICAL_DAYS)
backfill_policy_def_extended = BackfillPolicy.multi_run(max_partitions_per_run=BACKFILL_MAX_PARTITIONS_PER_RUN)


@dagster.asset(
    name="web_pre_aggregated_stats_backfill",
    group_name="web_analytics_v2",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_team_selection_v2"],
    partitions_def=backfill_partition_def,
    backfill_policy=backfill_policy_def_extended,
    metadata={"table": "web_pre_aggregated_stats"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "backfill": "true"},
    retry_policy=web_analytics_retry_policy_def,
)
def web_pre_aggregated_stats_backfill(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_pre_aggregated_stats",
        sql_generator=WEB_STATS_INSERT_SQL,
        cluster=cluster,
    )


@dagster.asset(
    name="web_pre_aggregated_bounces_backfill",
    group_name="web_analytics_v2",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_team_selection_v2"],
    partitions_def=backfill_partition_def,
    backfill_policy=backfill_policy_def_extended,
    metadata={"table": "web_pre_aggregated_bounces"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "backfill": "true"},
    retry_policy=web_analytics_retry_policy_def,
)
def web_pre_aggregated_bounces_backfill(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_pre_aggregated_bounces",
        sql_generator=WEB_BOUNCES_INSERT_SQL,
        cluster=cluster,
    )


web_pre_aggregate_backfill_job = dagster.define_asset_job(
    name="web_pre_aggregate_backfill_job",
    selection=["web_pre_aggregated_bounces_backfill", "web_pre_aggregated_stats_backfill"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(DAGSTER_WEB_JOB_TIMEOUT),
        "backfill": "true",
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": BACKFILL_MAX_CONCURRENT}),
)


def check_for_conflicting_jobs(context: dagster.ScheduleEvaluationContext) -> dagster.SkipReason | None:
    """Check for both concurrent backfill runs and regular web_pre_aggregate_job runs."""
    from dagster import DagsterRunStatus, RunsFilter

    # Check for concurrent backfill runs
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    # Check for active regular web pre-aggregate jobs (shared staging tables)
    regular_job_runs = context.instance.get_run_records(
        RunsFilter(
            job_name="web_pre_aggregate_job",
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.NOT_STARTED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(regular_job_runs) > 0:
        context.log.info(f"Skipping backfill due to {len(regular_job_runs)} active regular web_pre_aggregate_job run(s)")
        return dagster.SkipReason(
            "Skipping backfill because regular web_pre_aggregate_job is running (shared staging tables)"
        )

    return None


@dagster.schedule(
    cron_schedule="0 3 * * *",  # Daily at 3 AM UTC
    job=web_pre_aggregate_backfill_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "backfill": "true"},
)
def web_pre_aggregate_backfill_schedule(context: dagster.ScheduleEvaluationContext):
    # Check for conflicting jobs (both backfill and regular jobs)
    skip_reason = check_for_conflicting_jobs(context)
    if skip_reason:
        return skip_reason

    # Check if there are teams that actually need backfill (have missing data)
    try:
        # Create a proper mock context for the missing data check
        class MockExecutionContext:
            def __init__(self, log):
                self.log = log
                self.op_config = {}

            def get_tag(self, key: str) -> str | None:
                return None

        mock_context = MockExecutionContext(context.log)
        teams_needing_backfill = get_teams_with_missing_data(mock_context, lookback_days=BACKFILL_LOOKBACK_DAYS)

        if not teams_needing_backfill:
            context.log.info("No teams found with missing pre-aggregated data, skipping backfill")
            return dagster.SkipReason("No teams need backfill - all enabled teams have current data")

        context.log.info(f"Found {len(teams_needing_backfill)} teams needing backfill: {sorted(teams_needing_backfill)}")

    except Exception as e:
        context.log.warning(f"Failed to check for teams needing backfill, running anyway: {e}")
        import traceback
        context.log.debug(f"Full traceback: {traceback.format_exc()}")
        teams_needing_backfill = None

    # Run backfill for teams with missing data
    backfill_date = (datetime.now(UTC) - timedelta(days=BACKFILL_HISTORICAL_DAYS)).strftime("%Y-%m-%d")

    run_config = {
        "ops": {
            "web_pre_aggregated_stats_backfill": {
                "config": {
                    "extra_clickhouse_settings": "max_partitions_per_insert_block=1000"
                }
            },
            "web_pre_aggregated_bounces_backfill": {
                "config": {
                    "extra_clickhouse_settings": "max_partitions_per_insert_block=1000"
                }
            }
        }
    }

    # If we detected specific teams, add them to the config
    if teams_needing_backfill:
        run_config["ops"]["web_pre_aggregated_stats_backfill"]["config"]["team_ids"] = list(teams_needing_backfill)
        run_config["ops"]["web_pre_aggregated_bounces_backfill"]["config"]["team_ids"] = list(teams_needing_backfill)

    return dagster.RunRequest(
        partition_key=backfill_date,
        run_config=run_config,
    )
