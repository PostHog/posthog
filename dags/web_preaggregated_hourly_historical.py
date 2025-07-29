from datetime import datetime, UTC, timedelta
from collections.abc import Callable

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy
import structlog
from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    HISTORICAL_DAILY_CRON_SCHEDULE,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
)
from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster

from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
    DROP_PARTITION_SQL,
    WEB_STATS_HOURLY_HISTORICAL_SQL,
    WEB_BOUNCES_HOURLY_HISTORICAL_SQL,
)

logger = structlog.get_logger(__name__)

# Use same partition limits as daily jobs
max_partitions_per_run = 14
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)
partition_def = DailyPartitionsDefinition(start_date="2020-01-01")


def _get_partitions(cluster: ClickhouseCluster, table_name: str) -> list[str]:
    """Get all active partitions for a table."""
    partition_query = f"SELECT DISTINCT partition FROM system.parts WHERE table = '{table_name}' AND active = 1"
    partitions_result = cluster.any_host(lambda client: client.execute(partition_query)).result()
    return sorted([partition_row[0] for partition_row in partitions_result if partition_row and len(partition_row) > 0])


def drop_partitions_for_date_range(cluster: ClickhouseCluster, table_name: str, start_date: str, end_date: str) -> None:
    """Drop partitions for a specific date range (YYYY-MM-DD format)."""
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current_date < end_date_obj:
        partition_id = current_date.strftime("%Y%m%d")
        try:
            cluster.any_host(
                lambda client, pid=partition_id: client.execute(f"ALTER TABLE {table_name} DROP PARTITION '{pid}'")
            ).result()
            logger.info(f"Dropped partition {partition_id} from {table_name}")
        except Exception as e:
            logger.info(f"Partition {partition_id} doesn't exist or couldn't be dropped: {e}")

        current_date += timedelta(days=1)


def swap_partitions_from_staging(cluster: ClickhouseCluster, target_table: str, staging_table: str) -> None:
    """Atomically swap all partitions from staging to target table."""
    staging_partitions = _get_partitions(cluster, staging_table)
    logger.info(f"Swapping partitions {staging_partitions} from {staging_table} to {target_table}")

    for partition_id in staging_partitions:
        cluster.any_host(
            lambda client, pid=partition_id: client.execute(
                f"ALTER TABLE {target_table} REPLACE PARTITION '{pid}' FROM {staging_table}"
            )
        ).result()


def pre_aggregate_web_analytics_hourly_historical_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    cluster: ClickhouseCluster,
) -> None:
    """
    Pre-aggregate hourly historical web analytics data with daily partitions.

    This provides timezone-friendly data by using toStartOfHour() instead of toStartOfDay(),
    while maintaining daily partitions for easier management.
    """
    config = context.op_config
    team_ids = config.get("team_ids")
    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(
        f"Getting ready to pre-aggregate hourly historical {table_name} for {context.partition_time_window}"
    )

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    staging_table_name = f"{table_name}_staging"

    try:
        # 1. Clean staging table partitions for the date range
        context.log.info(f"Cleaning staging partitions for {date_start} to {date_end}")
        drop_partitions_for_date_range(cluster, staging_table_name, date_start, date_end)

        # 2. Generate hourly data into staging table
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids,
            settings=ch_settings,
            table_name=staging_table_name,
            granularity="hourly",  # Key: this uses toStartOfHour instead of toStartOfDay
        )

        context.log.info(f"Populating staging table with hourly data from {date_start} to {date_end}")
        context.log.info(insert_query)
        sync_execute(insert_query)

        # 3. Drop target table partitions for the date range
        context.log.info(f"Dropping target table partitions for {date_start} to {date_end}")
        drop_partitions_for_date_range(cluster, table_name, date_start, date_end)

        # 4. Atomically swap partitions from staging to target
        context.log.info(f"Swapping partitions from {staging_table_name} to {table_name}")
        swap_partitions_from_staging(cluster, table_name, staging_table_name)

        # 5. Clean up staging partitions
        context.log.info(f"Cleaning up staging partitions")
        drop_partitions_for_date_range(cluster, staging_table_name, date_start, date_end)

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate hourly historical {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_analytics_bounces_hourly_historical",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_bounces_hourly_historical"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_hourly_historical(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly historical bounce rate data with daily partitions.

    Solves timezone issues by providing hourly granularity while maintaining
    daily partitions for efficient management.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_hourly_historical_data(
        context=context,
        table_name="web_bounces_hourly_historical",
        sql_generator=WEB_BOUNCES_INSERT_SQL,
        cluster=cluster,
    )


@dagster.asset(
    name="web_analytics_stats_hourly_historical",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_stats_hourly_historical"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_hourly_historical(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly historical stats data with daily partitions.

    Solves timezone issues by providing hourly granularity while maintaining
    daily partitions for efficient management.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_hourly_historical_data(
        context=context,
        table_name="web_stats_hourly_historical",
        sql_generator=WEB_STATS_INSERT_SQL,
        cluster=cluster,
    )


# Historical hourly job for backfill and daily updates
web_pre_aggregate_hourly_historical_job = dagster.define_asset_job(
    name="web_analytics_hourly_historical_job",
    selection=["web_analytics_bounces_hourly_historical", "web_analytics_stats_hourly_historical"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    config={
        "execution": {
            "config": {
                "multiprocess": {
                    "max_concurrent": 1,
                }
            }
        }
    },
)


@dagster.schedule(
    cron_schedule=HISTORICAL_DAILY_CRON_SCHEDULE,
    job=web_pre_aggregate_hourly_historical_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_hourly_historical_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition, creating hourly historical data.
    This runs after the daily job to provide timezone-friendly hourly granularity.
    """
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "web_analytics_bounces_hourly_historical": {"config": {}},
                "web_analytics_stats_hourly_historical": {"config": {}},
            }
        },
    )
