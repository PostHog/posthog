import os
from datetime import datetime, timedelta
from functools import partial
from typing import Optional

import dagster
from dagster import Array, Backoff, DagsterRunStatus, Field, Jitter, RetryPolicy, RunsFilter, SkipReason

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG

TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS = os.getenv("TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS", 1 if DEBUG else 2)

INTRA_DAY_HOURLY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_INTRA_DAY_HOURLY_CRON_SCHEDULE", "*/20 * * * *")
HISTORICAL_DAILY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_HISTORICAL_DAILY_CRON_SCHEDULE", "0 1 * * *")

WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT = os.getenv("WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT", "2200")

# Dagster execution timeout constants (should be higher than ClickHouse timeouts)
DAGSTER_WEB_JOB_TIMEOUT = int(os.getenv("WEB_PREAGGREGATED_DAGSTER_JOB_TIMEOUT", "2400"))


web_analytics_retry_policy_def = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

# Shared ClickHouse settings for web analytics pre-aggregation
WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS = {
    "max_execution_time": WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT,
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
    "s3_truncate_on_insert": "1",
}

# Add higher partition limit for development environments (backfills)
if DEBUG:
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS["max_partitions_per_insert_block"] = "1000"


def format_clickhouse_settings(settings_dict: dict[str, str]) -> str:
    return ",".join([f"{key}={value}" for key, value in settings_dict.items()])


def merge_clickhouse_settings(base_settings: dict[str, str], extra_settings: Optional[str] = None) -> str:
    settings = base_settings.copy()

    if extra_settings:
        # Parse extra settings string and merge
        for setting in extra_settings.split(","):
            if "=" in setting:
                key, value = setting.strip().split("=", 1)
                settings[key.strip()] = value.strip()

    return format_clickhouse_settings(settings)


def get_partitions(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    table_name: str,
) -> list[str]:
    partition_query = f"SELECT DISTINCT partition FROM system.parts WHERE table = '{table_name}' AND active = 1"
    partitions_result = cluster.any_host(lambda client: client.execute(partition_query)).result()
    context.log.info(f"Found {len(partitions_result)} partitions for {table_name}: {partitions_result}")
    return sorted([partition_row[0] for partition_row in partitions_result if partition_row and len(partition_row) > 0])


def drop_partitions_for_date_range(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, table_name: str, start_date: str, end_date: str
) -> None:
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    # Calculate total partitions to drop for logging
    total_days = (end_date_obj - current_date).days
    context.log.info(
        f"Starting to drop {total_days} partitions from {table_name} for date range {start_date} to {end_date}"
    )

    dropped_count = 0
    skipped_count = 0

    while current_date < end_date_obj:
        partition_id = current_date.strftime("%Y%m%d")

        def drop_partition(client, pid):
            return client.execute(f"ALTER TABLE {table_name} DROP PARTITION '{pid}'")

        try:
            cluster.any_host(partial(drop_partition, pid=partition_id)).result()
            dropped_count += 1
            context.log.info(f"Dropped partition {partition_id} from {table_name} ({dropped_count}/{total_days})")
        except Exception:
            # Skip errors for non-existent partitions
            skipped_count += 1

        current_date += timedelta(days=1)

    context.log.info(
        f"Completed dropping partitions from {table_name}: {dropped_count} dropped, {skipped_count} skipped"
    )


def swap_partitions_from_staging(context: dagster.AssetExecutionContext, target_table: str, staging_table: str) -> None:
    if not context.partition_time_window:
        raise dagster.Failure("partition_time_window is required for partition swapping")

    # Generate partition list directly from time window (end is exclusive)
    start_datetime, end_datetime = context.partition_time_window
    partitions_to_swap = []
    current_date = start_datetime.date()
    end_date = end_datetime.date()

    while current_date < end_date:
        partition_id = current_date.strftime("%Y%m%d")
        partitions_to_swap.append(partition_id)
        current_date += timedelta(days=1)

    context.log.info(
        f"Generated {len(partitions_to_swap)} partitions to swap from time window {start_datetime.date()} to {end_datetime.date()}: {partitions_to_swap}"
    )
    context.log.info(f"Starting partition swap from {staging_table} to {target_table}")

    for i, partition_id in enumerate(partitions_to_swap, 1):
        context.log.info(f"Swapping partition {i}/{len(partitions_to_swap)}: {partition_id}")
        sync_execute(f"ALTER TABLE {target_table} REPLACE PARTITION '{partition_id}' FROM {staging_table}")
        context.log.info(f"Successfully swapped partition {partition_id}")

    context.log.info(
        f"Completed swapping all {len(partitions_to_swap)} partitions from {staging_table} to {target_table}"
    )


def clear_all_staging_partitions(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, staging_table: str
) -> None:
    all_partitions = get_partitions(context, cluster, staging_table)

    if not all_partitions:
        context.log.info(f"No partitions found in {staging_table}")
        return

    context.log.info(f"Starting to clear {len(all_partitions)} partitions from {staging_table}: {all_partitions}")

    def drop_partition(client, pid):
        return client.execute(f"ALTER TABLE {staging_table} DROP PARTITION '{pid}'")

    dropped_count = 0
    for i, partition_id in enumerate(all_partitions, 1):
        try:
            cluster.any_host(partial(drop_partition, pid=partition_id)).result()
            dropped_count += 1
            context.log.info(f"Dropped partition {partition_id} from {staging_table} ({i}/{len(all_partitions)})")
        except Exception:
            # Skip errors for non-existent partitions
            pass

    context.log.info(f"Completed clearing {staging_table}: {dropped_count}/{len(all_partitions)} partitions dropped")


# Shared config schema for daily processing
WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        is_required=False,
        description="List of team IDs to process - if not provided, uses ClickHouse dictionary configuration",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
}


def check_for_concurrent_runs(context: dagster.ScheduleEvaluationContext) -> Optional[SkipReason]:
    # Get the schedule name from the context
    schedule_name = context._schedule_name

    # Get the schedule definition from the repository to find the associated job
    schedule_def = context.repository_def.get_schedule_def(schedule_name)
    job_name = schedule_def.job_name

    run_records = context.instance.get_run_records(
        RunsFilter(
            job_name=job_name,
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.NOT_STARTED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(run_records) > 0:
        context.log.info(f"Skipping {job_name} due to {len(run_records)} active run(s)")
        return SkipReason(f"Skipping {job_name} run because another run of the same job is already active")

    return None
