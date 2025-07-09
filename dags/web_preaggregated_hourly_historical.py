from collections.abc import Callable
import os

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy
import structlog

from dags.common import JobOwners
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
)
from posthog.clickhouse.client import sync_execute
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_HOURLY_HISTORICAL_INSERT_SQL,
    WEB_BOUNCES_HOURLY_HISTORICAL_INSERT_SQL,
)

logger = structlog.get_logger(__name__)

# Historical processing can handle more partitions since it's for backfill/comparison
max_partitions_per_run = int(os.getenv("DAGSTER_WEB_PREAGGREGATED_HISTORICAL_MAX_PARTITIONS_PER_RUN", 7))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)

partition_def = DailyPartitionsDefinition(start_date="2020-01-01")


def pre_aggregate_web_analytics_hourly_historical(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
) -> None:
    """
    Pre-aggregate historical web analytics data in hourly buckets for accuracy comparison.

    Args:
        context: Dagster execution context
        table_name: Target table name (web_stats_hourly_historical or web_bounces_hourly_historical)
        sql_generator: Function to generate SQL query
    """
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(
        f"Getting ready to pre-aggregate {table_name} hourly historical for {context.partition_time_window}"
    )

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d %H:%M:%S")
    date_end = end_datetime.strftime("%Y-%m-%d %H:%M:%S")

    try:
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids if team_ids else TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
            settings=ch_settings,
            table_name=table_name,
        )

        # Log query for debugging
        context.log.info(f"Executing query for {table_name}: {insert_query[:500]}...")

        sync_execute(insert_query)
        context.log.info(f"Successfully pre-aggregated {table_name} for {context.partition_time_window}")

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_analytics_bounces_hourly_historical",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_historical_tables"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_bounces_hourly_historical"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_hourly_historical(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Historical hourly bounce rate data for web analytics accuracy comparison.

    Aggregates bounce rate, session duration, and other session-level metrics
    by various dimensions (UTM parameters, geography, device info, etc.) in hourly buckets.
    This data is used to test the hypothesis that hourly aggregation provides better accuracy
    than daily aggregation.
    """
    return pre_aggregate_web_analytics_hourly_historical(
        context=context,
        table_name="web_bounces_hourly_historical",
        sql_generator=WEB_BOUNCES_HOURLY_HISTORICAL_INSERT_SQL,
    )


@dagster.asset(
    name="web_analytics_stats_table_hourly_historical",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_historical_tables"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_stats_hourly_historical"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_hourly_historical(context: dagster.AssetExecutionContext) -> None:
    """
    Historical hourly aggregated dimensional data with pageviews and unique user counts.

    Aggregates pageview counts, unique visitors, and unique sessions
    by various dimensions (pathnames, UTM parameters, geography, device info, etc.) in hourly buckets.
    This data is used to test the hypothesis that hourly aggregation provides better accuracy
    than daily aggregation.
    """
    return pre_aggregate_web_analytics_hourly_historical(
        context=context,
        table_name="web_stats_hourly_historical",
        sql_generator=WEB_STATS_HOURLY_HISTORICAL_INSERT_SQL,
    )


# Job for hourly historical aggregation
web_pre_aggregate_hourly_historical_job = dagster.define_asset_job(
    name="web_analytics_hourly_historical_job",
    selection=["web_analytics_bounces_hourly_historical", "web_analytics_stats_table_hourly_historical"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
    },
    # Sequential execution for better resource management
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
