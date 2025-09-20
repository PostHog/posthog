from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import dagster
from dagster import Field

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.sql import (
    REPLACE_WEB_BOUNCES_HOURLY_STAGING_SQL,
    REPLACE_WEB_STATS_HOURLY_STAGING_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
)

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    DAGSTER_WEB_JOB_TIMEOUT,
    INTRA_DAY_HOURLY_CRON_SCHEDULE,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
    check_for_concurrent_runs,
    merge_clickhouse_settings,
    web_analytics_retry_policy_def,
)

WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA = {
    **WEB_ANALYTICS_CONFIG_SCHEMA,
    "hours_back": Field(
        float,
        default_value=23,
        description="Number of hours back to process data for",
    ),
}

REPLACE_TEMPLATES_BY_TABLE_NAME = {
    "web_bounces_hourly_staging": REPLACE_WEB_BOUNCES_HOURLY_STAGING_SQL,
    "web_stats_hourly_staging": REPLACE_WEB_STATS_HOURLY_STAGING_SQL,
}


def recreate_table(cluster: ClickhouseCluster, table_name: str) -> None:
    """Recreate table on all hosts."""
    if table_name not in REPLACE_TEMPLATES_BY_TABLE_NAME:
        raise ValueError(f"There is no SQL statement for replacing the table {table_name}")
    replace_table_sql = REPLACE_TEMPLATES_BY_TABLE_NAME[table_name]
    cluster.map_hosts_by_roles(
        lambda client: client.execute(replace_table_sql()), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ).result()


def exchange_tables(cluster: ClickhouseCluster, source_table_name: str, target_table_name: str) -> None:
    """Exchange tables on all hosts."""
    cluster.map_hosts_by_roles(
        lambda client: client.execute(f"EXCHANGE TABLES {source_table_name} AND {target_table_name}"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ).result()


def pre_aggregate_web_analytics_hourly_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    cluster: ClickhouseCluster,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids")

    extra_settings = config.get("extra_clickhouse_settings", "")
    hours_back = config["hours_back"]
    clickhouse_settings = merge_clickhouse_settings(WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS, extra_settings)

    # Process the last N hours to handle any late-arriving data
    # Align with hour boundaries to match toStartOfHour() used in SQL, where we convert this to UTC,
    # so this is just to make sure we get complete hours
    now = datetime.now(UTC)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    date_end = (current_hour + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    date_start = (current_hour - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S")

    # Use a staging table to avoid downtime when swapping data
    staging_table_name = f"{table_name}_staging"

    # First, populate the staging table
    insert_query = sql_generator(
        date_start=date_start,
        date_end=date_end,
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=staging_table_name,
        granularity="hourly",
    )

    context.log.info(f"Recreating staging table {staging_table_name}")
    recreate_table(cluster, staging_table_name)

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(f"Processing hourly data from {date_start} to {date_end}")
    context.log.info(insert_query)

    # Insert into staging table
    sync_execute(insert_query)

    context.log.info(f"Swapping data from {staging_table_name} to {table_name}")
    exchange_tables(cluster, staging_table_name, table_name)


@dagster.asset(
    name="web_analytics_bounces_hourly",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    metadata={"table": "web_bounces_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly bounce rate data for web analytics with 24h TTL. Updates every 5 minutes.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_hourly_data(
        context=context, table_name="web_bounces_hourly", sql_generator=WEB_BOUNCES_INSERT_SQL, cluster=cluster
    )


@dagster.asset(
    name="web_analytics_stats_table_hourly",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    metadata={"table": "web_stats_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly aggregated dimensional data with pageviews and unique user counts with 24h TTL. Updates every 5 minutes.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_hourly_data(
        context=context,
        table_name="web_stats_hourly",
        sql_generator=WEB_STATS_INSERT_SQL,
        cluster=cluster,
    )


web_pre_aggregate_current_day_hourly_job = dagster.define_asset_job(
    name="web_pre_aggregate_current_day_hourly_job",
    selection=dagster.AssetSelection.assets(
        "web_analytics_bounces_hourly",
        "web_analytics_stats_table_hourly",
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(DAGSTER_WEB_JOB_TIMEOUT),
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 1}),
)


@dagster.schedule(
    cron_schedule=INTRA_DAY_HOURLY_CRON_SCHEDULE,
    job=web_pre_aggregate_current_day_hourly_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_current_day_hourly_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Creates real-time web analytics pre-aggregated data with 24h TTL for real-time analytics.
    """

    # Check for existing runs of the same job to prevent concurrent execution
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_bounces_hourly": {"config": {}},
                "web_analytics_stats_table_hourly": {"config": {}},
            }
        },
    )
