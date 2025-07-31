import os
import dagster
from datetime import datetime, timedelta
from functools import partial
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG
from typing import Optional
from dagster import Backoff, Field, Array, Jitter, RetryPolicy

TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS = os.getenv("TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS", 1 if DEBUG else 2)

INTRA_DAY_HOURLY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_INTRA_DAY_HOURLY_CRON_SCHEDULE", "*/10 * * * *")
HISTORICAL_DAILY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_HISTORICAL_DAILY_CRON_SCHEDULE", "0 1 * * *")

DAILY_MAX_EXECUTION_TIME = os.getenv("WEB_PREAGGREGATED_DAILY_MAX_EXECUTION_TIME", "1600")
INTRA_DAY_HOURLY_MAX_EXECUTION_TIME = os.getenv("WEB_PREAGGREGATED_INTRA_DAY_HOURLY_MAX_EXECUTION_TIME", "900")

web_analytics_retry_policy_def = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

# Shared ClickHouse settings for web analytics pre-aggregation
CLICKHOUSE_SETTINGS = {
    "max_execution_time": DAILY_MAX_EXECUTION_TIME,
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
    "s3_truncate_on_insert": "1",
}

CLICKHOUSE_SETTINGS_HOURLY = {
    "max_execution_time": INTRA_DAY_HOURLY_MAX_EXECUTION_TIME,
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
}

# Add higher partition limit for development environments (backfills)
if DEBUG:
    CLICKHOUSE_SETTINGS["max_partitions_per_insert_block"] = "1000"
    CLICKHOUSE_SETTINGS_HOURLY["max_partitions_per_insert_block"] = "1000"


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


def get_partitions(context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, table_name: str) -> list[str]:
    partition_query = f"SELECT DISTINCT partition FROM system.parts WHERE table = '{table_name}' AND active = 1"
    partitions_result = cluster.any_host(lambda client: client.execute(partition_query)).result()
    context.log.info(f"Found {len(partitions_result)} partitions for {table_name}: {partitions_result}")
    return sorted([partition_row[0] for partition_row in partitions_result if partition_row and len(partition_row) > 0])


def drop_partitions_for_date_range(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, table_name: str, start_date: str, end_date: str
) -> None:
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current_date < end_date_obj:
        partition_id = current_date.strftime("%Y%m%d")

        def drop_partition(client, pid):
            return client.execute(f"ALTER TABLE {table_name} DROP PARTITION '{pid}'")

        try:
            cluster.any_host(partial(drop_partition, pid=partition_id)).result()
            context.log.info(f"Dropped partition {partition_id} from {table_name}")
        except Exception as e:
            context.log.info(f"Partition {partition_id} doesn't exist or couldn't be dropped: {e}")

        current_date += timedelta(days=1)


def swap_partitions_from_staging(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, target_table: str, staging_table: str
) -> None:
    staging_partitions = get_partitions(context, cluster, staging_table)
    context.log.info(f"Swapping partitions {staging_partitions} from {staging_table} to {target_table}")

    def replace_partition(client, pid):
        return client.execute(f"ALTER TABLE {target_table} REPLACE PARTITION '{pid}' FROM {staging_table}")

    for partition_id in staging_partitions:
        cluster.any_host(partial(replace_partition, pid=partition_id)).result()


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
