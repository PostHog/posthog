from datetime import datetime, UTC
from collections.abc import Callable

import dagster
from dagster import Field, Array
from clickhouse_driver import Client
from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    WEB_OVERVIEW_METRICS_DAILY_SQL,
    DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    WEB_OVERVIEW_INSERT_SQL,
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
        default_value="max_execution_time=240, max_bytes_before_external_group_by=21474836480, distributed_aggregation_memory_efficient=1",
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

    # We'll be handling this year data for our tests.
    insert_query = sql_generator(
        date_start="2025-01-01",
        date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
    )

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(insert_query)

    sync_execute(insert_query)


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    description="Creates the tables needed for web analytics preaggregated data.",
)
def web_analytics_preaggregated_tables(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def create_tables(client: Client):
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name="web_overview_daily"))
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_overview_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_overview_daily"},
)
def web_overview_daily(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Daily aggregated for the top overview tiles for web analytics which includes total pageviews, bounce rate, and average session duration.
    """
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_overview_daily",
        sql_generator=WEB_OVERVIEW_INSERT_SQL,
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_stats_daily"},
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
)
def recreate_web_analytics_preaggregated_internal_data_daily(context: dagster.ScheduleEvaluationContext):
    """
    Recreates the web_analytics pre-aggregated data for our internal team only
    while we test the integration. The usage of pre-aggregated tables is controlled
    by a query modifier AND is behind a feature flag.
    """
    return dagster.RunRequest(
        run_config={
            "team_ids": [2]  # We only care about the scheduler in prod so we're good with magic team
        },
    )
