from datetime import datetime, UTC, timedelta
from collections.abc import Callable
from typing import Optional

import dagster
from dagster import Field, Array, DailyPartitionsDefinition, RetryPolicy, Backoff, Jitter
from clickhouse_driver import Client
from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    DISTRIBUTED_WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.clickhouse.cluster import ClickhouseCluster


# Daily partitions starting from 2020-01-01
daily_partitions = DailyPartitionsDefinition(start_date="2020-01-01")

# Retry policy for ClickHouse operations
clickhouse_retry_policy = RetryPolicy(
    max_retries=3,
    delay=Backoff.exponential(base_delay=30, max_delay=300),
    jitter=Jitter.plus_minus(5),
)

# Default ClickHouse settings with improved memory management
DEFAULT_CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1200",
    "max_bytes_before_external_group_by": "21474836480",
    "distributed_aggregation_memory_efficient": "1",
    "max_memory_usage": "53687091200",  # 50GB default
    "max_threads": "8",
    "join_algorithm": "hash",
    "optimize_aggregation_in_order": "1",
}

# High-performance settings for recreate_all job
HIGH_PERFORMANCE_CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1600",
    "max_bytes_before_external_group_by": "51474836480",
    "distributed_aggregation_memory_efficient": "1",
    "max_memory_usage": "107374182400",  # 100GB for recreate_all
    "max_threads": "16",
    "join_algorithm": "hash",
    "optimize_aggregation_in_order": "1",
}


def format_clickhouse_settings(settings_dict: dict[str, str]) -> str:
    """Convert settings dictionary to ClickHouse settings string."""
    return ",".join([f"{key}={value}" for key, value in settings_dict.items()])


def merge_clickhouse_settings(base_settings: dict[str, str], extra_settings: Optional[str] = None) -> str:
    """Merge base settings with optional extra settings string."""
    settings = base_settings.copy()
    
    if extra_settings:
        # Parse extra settings string and merge
        for setting in extra_settings.split(","):
            if "=" in setting:
                key, value = setting.strip().split("=", 1)
                settings[key.strip()] = value.strip()
    
    return format_clickhouse_settings(settings)


WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - if empty we will process for teams [1,2] only",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
    "use_high_performance_settings": Field(
        bool,
        default_value=False,
        description="Use high-performance settings for large data processing",
    ),
}


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    partition_date: Optional[str] = None,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", [1, 2])
    extra_settings = config.get("extra_clickhouse_settings", "")
    use_high_performance = config.get("use_high_performance_settings", False)
    
    # Choose base settings
    base_settings = HIGH_PERFORMANCE_CLICKHOUSE_SETTINGS if use_high_performance else DEFAULT_CLICKHOUSE_SETTINGS
    clickhouse_settings = merge_clickhouse_settings(base_settings, extra_settings)
    
    # Determine date range
    if partition_date:
        # For partitioned runs, process single day
        date_start = partition_date
        date_end = (datetime.strptime(partition_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        # For recreate_all, process full history
        date_start = "2020-01-01"
        date_end = datetime.now(UTC).strftime("%Y-%m-%d")

    insert_query = sql_generator(
        date_start=date_start,
        date_end=date_end,
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
    )

    # Log the query and settings for debugging
    context.log.info(f"Processing {table_name} for date range {date_start} to {date_end}")
    context.log.info(f"ClickHouse settings: {clickhouse_settings}")
    context.log.info(f"Query: {insert_query}")

    sync_execute(insert_query)


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    description="Creates the tables needed for web analytics preaggregated data.",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=clickhouse_retry_policy,
)
def web_analytics_preaggregated_tables(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def drop_tables(client: Client):
        client.execute("DROP TABLE IF EXISTS web_stats_daily SYNC")
        client.execute("DROP TABLE IF EXISTS web_bounces_daily SYNC")

    def create_tables(client: Client):
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily"))
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_BOUNCES_DAILY_SQL())

    cluster.map_all_hosts(drop_tables).result()
    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_bounces_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    partitions_def=daily_partitions,
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=clickhouse_retry_policy,
)
def web_bounces_daily(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Daily bounce rate data for web analytics.
    """
    partition_date = context.partition_key if context.has_partition_key else None
    return pre_aggregate_web_analytics_data(
        context=context, 
        table_name="web_bounces_daily", 
        sql_generator=WEB_BOUNCES_INSERT_SQL,
        partition_date=partition_date,
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    partitions_def=daily_partitions,
    metadata={"table": "web_stats_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=clickhouse_retry_policy,
)
def web_stats_daily(context: dagster.AssetExecutionContext) -> None:
    """
    Aggregated dimensional data with pageviews and unique user counts.
    """
    partition_date = context.partition_key if context.has_partition_key else None
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
        partition_date=partition_date,
    )


# Daily incremental job with concurrency control - only data insertion
web_analytics_daily_data_job = dagster.define_asset_job(
    name="web_analytics_daily_data",
    selection=[web_analytics_bounces_daily, web_analytics_stats_table_daily],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config={
        "execution": {
            "config": {
                "multiprocess": {
                    "max_concurrent": 1,  # Prevent overwhelming ClickHouse cluster
                }
            }
        }
    },
)

# Table creation job for initial setup
web_analytics_table_setup_job = dagster.define_asset_job(
    name="web_analytics_table_setup",
    selection=[web_analytics_preaggregated_tables],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)

# Simple recreate all job - no partitions, processes everything
recreate_all_web_analytics_job = dagster.define_asset_job(
    name="recreate_all_web_analytics",
    selection=dagster.AssetSelection.groups("web_analytics"),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config={
        "execution": {
            "config": {
                "multiprocess": {
                    "max_concurrent": 1,  # Prevent overwhelming ClickHouse cluster
                }
            }
        }
    },
)


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job=web_analytics_daily_data_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def recreate_web_analytics_preaggregated_internal_data_daily(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition.
    This is used to generate the pre-aggregated tables for faster queries on web analytics.
    The usage of pre-aggregated tables is controlled by a query modifier AND is behind a feature flag.
    """
    # Get yesterday's partition
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "web_analytics_bounces_daily": {"config": {}},
                "web_analytics_stats_table_daily": {"config": {}},
            }
        },
    )
