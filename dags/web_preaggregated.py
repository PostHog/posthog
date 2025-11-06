import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.sql import (
    REPLACE_WEB_BOUNCES_V2_STAGING_SQL,
    REPLACE_WEB_STATS_V2_STAGING_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.settings import DEBUG, TEST

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    DAGSTER_WEB_JOB_TIMEOUT,
    HISTORICAL_DAILY_CRON_SCHEDULE,
    INTRA_DAY_HOURLY_CRON_SCHEDULE,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
    check_for_concurrent_runs,
    clear_all_staging_partitions,
    merge_clickhouse_settings,
    recreate_staging_table,
    swap_partitions_from_staging,
    sync_partitions_on_replicas,
    web_analytics_retry_policy_def,
)

MAX_PARTITIONS_PER_RUN_ENV_VAR = "DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN"
max_partitions_per_run = int(os.getenv(MAX_PARTITIONS_PER_RUN_ENV_VAR, 1))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)
partition_def = DailyPartitionsDefinition(start_date="2024-01-01", end_offset=1)

REPLACE_TEMPLATES_BY_STAGING_TABLE_NAME = {
    "web_pre_aggregated_stats_staging": REPLACE_WEB_STATS_V2_STAGING_SQL,
    "web_pre_aggregated_bounces_staging": REPLACE_WEB_BOUNCES_V2_STAGING_SQL,
}


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
        # 1. Recreate staging table
        if staging_table_name not in REPLACE_TEMPLATES_BY_STAGING_TABLE_NAME:
            raise dagster.Failure(f"No REPLACE TABLE function found for {staging_table_name}")

        replace_sql_func = REPLACE_TEMPLATES_BY_STAGING_TABLE_NAME[staging_table_name]
        recreate_staging_table(context, cluster, staging_table_name, replace_sql_func)

        # 2. Write data into staging table
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

        # 3. Sync replicas before partition swapping to ensure consistency
        sync_partitions_on_replicas(context, cluster, staging_table_name)

        # 4. Atomically swap partitions from staging to target
        context.log.info(f"Swapping partitions from {staging_table_name} to {table_name}")
        swap_partitions_from_staging(context, cluster, table_name, staging_table_name)

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


def ensure_web_analytics_tables_exist(context: dagster.ScheduleEvaluationContext) -> None:
    if TEST:
        return

    try:
        stats_sql = REPLACE_WEB_STATS_V2_STAGING_SQL().replace("_staging", "")
        context.log.info("Ensuring web_pre_aggregated_stats exists with production schema")
        sync_execute(stats_sql)

        bounces_sql = REPLACE_WEB_BOUNCES_V2_STAGING_SQL().replace("_staging", "")
        context.log.info("Ensuring web_pre_aggregated_bounces exists with production schema")
        sync_execute(bounces_sql)

        context.log.info("Web analytics tables are ready with production schema")
    except Exception as e:
        context.log.warning(f"Error ensuring tables exist: {e}")
        # Don't fail the schedule if table creation fails - let the job handle it


@dagster.schedule(
    cron_schedule="*/10 * * * *",
    job=web_pre_aggregate_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    default_status=dagster.DefaultScheduleStatus.RUNNING if DEBUG else dagster.DefaultScheduleStatus.STOPPED,
)
def web_analytics_v2_backfill_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Schedule that materializes web analytics v2 assets for today's partition.
    Only runs in DEBUG mode so we don't overload ClickHouse in production.

    Triggers materialization if no recent runs in the last 6 hours.
    """

    if not DEBUG:
        return dagster.SkipReason("Schedule only runs in DEBUG mode")

    # Ensure tables exist with production schema before running backfill
    ensure_web_analytics_tables_exist(context)

    try:
        # Check for recent runs
        instance = context.instance
        runs = instance.get_runs(
            filters=dagster.RunsFilter(
                tags={"triggered_by": "backfill_schedule"},
                statuses=[dagster.DagsterRunStatus.SUCCESS],
            ),
            limit=1,
        )

        hours_since_last_run = None
        if runs:
            run_stats = instance.get_run_stats(runs[0].run_id)
            last_run_time = run_stats.end_time
            if last_run_time:
                hours_since_last_run = (datetime.now(UTC).timestamp() - last_run_time) / 3600

        # Check if we should trigger backfill
        if hours_since_last_run is not None and hours_since_last_run < 6:
            return dagster.SkipReason(f"Last run was {hours_since_last_run:.1f}h ago (< 6h threshold)")

        reason = (
            "No previous runs found"
            if hours_since_last_run is None
            else f"Last run was {hours_since_last_run:.1f}h ago"
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        context.log.info(f"Triggering web analytics v2 materialization for today ({today}): {reason}")

        # Return a single run request for today's partition
        return dagster.RunRequest(
            run_key=f"web_analytics_v2_backfill_{datetime.now(UTC).timestamp()}",
            partition_key=today,
            tags={
                "triggered_by": "backfill_schedule",
                "triggered_at": datetime.now(UTC).isoformat(),
                "reason": reason,
            },
        )

    except Exception as e:
        return dagster.SkipReason(f"Error checking backfill conditions: {str(e)}")
