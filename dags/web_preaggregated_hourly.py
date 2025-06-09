from datetime import datetime, UTC, timedelta
from collections.abc import Callable

import dagster
from dagster import Field, Array
from clickhouse_driver import Client
from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    DISTRIBUTED_WEB_BOUNCES_HOURLY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_HOURLY_SQL,
    DISTRIBUTED_WEB_STATS_HOURLY_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.clickhouse.cluster import ClickhouseCluster


WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - if empty we will process for default teams only",
    ),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=300,max_bytes_before_external_group_by=21474836480,distributed_aggregation_memory_efficient=1",
        description="ClickHouse execution settings",
    ),
    "hours_back": Field(
        float,
        default_value=23,
        description="Number of hours back to process data for",
    ),
}

# TODO: Remove this once we're fully rolled out but this is better than defaulting to all teams
DEFAULT_TEAM_IDS = [2, 55348, 47074]


def pre_aggregate_web_analytics_hourly_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", DEFAULT_TEAM_IDS)
    clickhouse_settings = config["clickhouse_settings"]
    hours_back = config["hours_back"]

    # Process the last N hours to handle any late-arriving data
    # Align with hour boundaries to match toStartOfHour() used in SQL, where we convert this to UTC,
    # so this is just to make sure we get complete hours
    now = datetime.now(UTC)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    date_end = (current_hour + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    date_start = (current_hour - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M:%S")

    insert_query = sql_generator(
        date_start=date_start,
        date_end=date_end,
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
        granularity="hourly",
    )

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(f"Processing hourly data from {date_start} to {date_end}")
    context.log.info(insert_query)

    sync_execute(insert_query)


@dagster.asset(
    name="web_analytics_preaggregated_hourly_tables",
    group_name="web_analytics_hourly",
    description="Creates the hourly tables needed for web analytics preaggregated data with 24h TTL for real-time analytics.",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_preaggregated_hourly_tables(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def drop_tables(client: Client):
        client.execute("DROP TABLE IF EXISTS web_stats_hourly SYNC")
        client.execute("DROP TABLE IF EXISTS web_bounces_hourly SYNC")

    def create_tables(client: Client):
        client.execute(WEB_STATS_HOURLY_SQL())
        client.execute(WEB_BOUNCES_HOURLY_SQL())

        client.execute(DISTRIBUTED_WEB_STATS_HOURLY_SQL())
        client.execute(DISTRIBUTED_WEB_BOUNCES_HOURLY_SQL())

    cluster.map_all_hosts(drop_tables).result()
    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_bounces_hourly",
    group_name="web_analytics_hourly",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_tables"],
    metadata={"table": "web_bounces_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly bounce rate data for web analytics with 24h TTL. Updates every 5 minutes.
    """

    def truncate(client: Client):
        client.execute("TRUNCATE TABLE web_bounces_hourly SYNC")

    cluster.map_all_hosts(truncate).result()

    return pre_aggregate_web_analytics_hourly_data(
        context=context, table_name="web_bounces_hourly", sql_generator=WEB_BOUNCES_INSERT_SQL
    )


@dagster.asset(
    name="web_analytics_stats_table_hourly",
    group_name="web_analytics_hourly",
    config_schema=WEB_ANALYTICS_HOURLY_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_hourly_tables"],
    metadata={"table": "web_stats_hourly"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_hourly(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Hourly aggregated dimensional data with pageviews and unique user counts with 24h TTL. Updates every 5 minutes.
    """

    def truncate(client: Client):
        client.execute("TRUNCATE TABLE web_stats_hourly SYNC")

    cluster.map_all_hosts(truncate).result()

    return pre_aggregate_web_analytics_hourly_data(
        context=context,
        table_name="web_stats_hourly",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


web_pre_aggregate_current_day_hourly_job = dagster.define_asset_job(
    name="web_pre_aggregate_current_day_hourly_job",
    selection=dagster.AssetSelection.assets(
        "web_analytics_bounces_hourly",
        "web_analytics_stats_table_hourly",
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="*/10 * * * *",
    job=web_pre_aggregate_current_day_hourly_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_current_day_hourly_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Creates real-time web analytics pre-aggregated data with 24h TTL for real-time analytics.
    """

    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_bounces_hourly": {"config": {"team_ids": DEFAULT_TEAM_IDS}},
                "web_analytics_stats_table_hourly": {"config": {"team_ids": DEFAULT_TEAM_IDS}},
            }
        },
    )
