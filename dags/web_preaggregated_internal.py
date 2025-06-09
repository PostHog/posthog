from datetime import datetime, UTC
from collections.abc import Callable

import dagster
from dagster import Field, Array
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


WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - if empty we will process for teams [1,2] only",
    ),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=1200,max_bytes_before_external_group_by=21474836480,distributed_aggregation_memory_efficient=1",
        description="ClickHouse execution settings",
    ),
}


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", [1, 2])
    clickhouse_settings = config["clickhouse_settings"]

    # We'll be handling a fixed date range for our internal tests that gets the full history
    insert_query = sql_generator(
        date_start="2020-01-01",
        date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
        granularity="daily",
    )

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(insert_query)

    sync_execute(insert_query)


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    description="Creates the tables needed for web analytics preaggregated data.",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
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
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_daily(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Daily bounce rate data for web analytics. Intended for internal use on other queries
    """
    return pre_aggregate_web_analytics_data(
        context=context, table_name="web_bounces_daily", sql_generator=WEB_BOUNCES_INSERT_SQL
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_stats_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_daily(context: dagster.AssetExecutionContext) -> None:
    """
    Aggregated dimensional data with pageviews and unique user counts. This is used by the breakdown tiles except the path-specific ones.
    """
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


recreate_web_pre_aggregated_data_job = dagster.define_asset_job(
    name="recreate_web_pre_aggregated_data",
    selection=dagster.AssetSelection.groups("web_analytics"),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job=recreate_web_pre_aggregated_data_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def recreate_web_analytics_preaggregated_internal_data_daily(context: dagster.ScheduleEvaluationContext):
    """
    Recreates the web_analytics pre-aggregated data for our internal team only
    while we test the integration. The usage of pre-aggregated tables is controlled
    by a query modifier AND is behind a feature flag.
    """
    team_ids = [2]

    return dagster.RunRequest(
        run_config={
            "ops": {
                "web_analytics_bounces_daily": {"config": {"team_ids": team_ids}},
                "web_analytics_stats_table_daily": {"config": {"team_ids": team_ids}},
            }
        },
    )
