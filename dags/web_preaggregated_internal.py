from datetime import datetime, UTC, timedelta
from collections.abc import Callable
from typing import Optional
import structlog

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

logger = structlog.get_logger(__name__)


# Concurrency keys for different types of web analytics operations
# These keys need to be configured in the Dagster instance configuration
# to set actual limits. The keys here are just identifiers.
WEB_ANALYTICS_CONCURRENCY_KEYS = {
    "bounces_heavy_query": "web_analytics_bounces_heavy_query",
    "stats_heavy_query": "web_analytics_stats_heavy_query", 
    "table_setup": "web_analytics_table_setup",
}


daily_partitions = DailyPartitionsDefinition(start_date="2020-01-01")

clickhouse_retry_policy = RetryPolicy(
    max_retries=3,
    delay=30,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

CLICKHOUSE_SETTINGS = {
    "max_execution_time": "1600",
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
}


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


WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - if empty, processes all teams",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
}


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    partition_date: Optional[str] = None,
) -> None:
    """
    Pre-aggregate web analytics data for a given table and date range.
    
    Args:
        context: Dagster execution context
        table_name: Target table name (web_stats_daily or web_bounces_daily)
        sql_generator: Function to generate SQL query
        partition_date: Date to process (YYYY-MM-DD format), if None processes full history
    """
    config = context.op_config
    team_ids = config.get("team_ids", [])
    extra_settings = config.get("extra_clickhouse_settings", "")
    
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, extra_settings)
    
    if partition_date:
        # For partitioned runs, process single day
        try:
            parsed_date = datetime.strptime(partition_date, "%Y-%m-%d")
            date_start = partition_date
            date_end = (parsed_date + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError as e:
            logger.error("invalid_partition_date", partition_date=partition_date, error=str(e))
            raise dagster.Failure(f"Invalid partition date format: {partition_date}") from e
    else:
        # For recreate_all, process full history
        date_start = "2020-01-01"
        date_end = datetime.now(UTC).strftime("%Y-%m-%d")

    try:
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids if team_ids else None,
            settings=ch_settings,
            table_name=table_name,
        )

        # Intentionally log query details for debugging
        logger.info(
            "executing_web_analytics_pre_aggregation",
            table_name=table_name,
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids if team_ids else "all_teams",
            partition_date=partition_date,
            settings=ch_settings,
        )

        sync_execute(insert_query)
        
        logger.info(
            "web_analytics_pre_aggregation_completed",
            table_name=table_name,
            date_start=date_start,
            date_end=date_end,
        )
        
    except Exception as e:
        logger.error(
            "web_analytics_pre_aggregation_failed",
            table_name=table_name,
            date_start=date_start,
            date_end=date_end,
            settings=ch_settings,
            team_ids=team_ids,
            error=str(e),
        )
        raise dagster.Failure(f"Failed to pre-aggregate {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    retry_policy=clickhouse_retry_policy,
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    op_tags={"dagster/concurrency_key": WEB_ANALYTICS_CONCURRENCY_KEYS["table_setup"]},
)
def web_analytics_preaggregated_tables(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    """
    Create web analytics pre-aggregated tables on all ClickHouse hosts.
    
    This asset creates both local and distributed tables for web analytics.
    """
    def drop_tables(client: Client):
        try:
            client.execute("DROP TABLE IF EXISTS web_stats_daily SYNC")
            client.execute("DROP TABLE IF EXISTS web_bounces_daily SYNC")
            logger.info("dropped_existing_tables", host=client.connection.host)
        except Exception as e:
            logger.error("failed_to_drop_tables", host=client.connection.host, error=str(e))
            raise

    def create_tables(client: Client):
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily"))

        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_BOUNCES_DAILY_SQL())

    try:
        cluster.map_all_hosts(drop_tables).result()
        cluster.map_all_hosts(create_tables).result()
        logger.info("web_analytics_tables_setup_completed")
        return True
    except Exception as e:
        logger.error("web_analytics_tables_setup_failed", error=str(e))
        raise dagster.Failure(f"Failed to setup web analytics tables: {str(e)}") from e


@dagster.asset(
    name="web_analytics_bounces_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    partitions_def=daily_partitions,
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=clickhouse_retry_policy,
    op_tags={"dagster/concurrency_key": WEB_ANALYTICS_CONCURRENCY_KEYS["bounces_heavy_query"]},
)
def web_bounces_daily(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Daily bounce rate data for web analytics.
    
    Aggregates bounce rate, session duration, and other session-level metrics
    by various dimensions (UTM parameters, geography, device info, etc.).
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
    op_tags={"dagster/concurrency_key": WEB_ANALYTICS_CONCURRENCY_KEYS["stats_heavy_query"]},
)
def web_stats_daily(context: dagster.AssetExecutionContext) -> None:
    """
    Aggregated dimensional data with pageviews and unique user counts.
    
    Aggregates pageview counts, unique visitors, and unique sessions
    by various dimensions (pathnames, UTM parameters, geography, device info, etc.).
    """
    partition_date = context.partition_key if context.has_partition_key else None
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
        partition_date=partition_date,
    )


# Daily incremental job with asset-level concurrency control
web_analytics_daily_data_job = dagster.define_asset_job(
    name="web_analytics_daily_data",
    selection=["web_analytics_bounces_daily", "web_analytics_stats_table_daily"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config={
        "execution": {
            "config": {
                "multiprocess": {
                    # Allow more concurrency to speed up the Dagster job overhead while respecting asset-level concurrency
                    "max_concurrent": 2,
                }
            }
        }
    },
)

web_analytics_table_setup_job = dagster.define_asset_job(
    name="web_analytics_table_setup",
    selection=["web_analytics_preaggregated_tables"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)

# Recreate all job with higher concurrency for backfills
recreate_all_web_analytics_job = dagster.define_asset_job(
    name="recreate_all_web_analytics",
    selection=dagster.AssetSelection.groups("web_analytics"),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config={
        "execution": {
            "config": {
                "multiprocess": {
                    # Allow more concurrency to speed up the Dagster job overhead while respecting asset-level concurrency
                    "max_concurrent": 2,
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
