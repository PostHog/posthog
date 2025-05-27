from datetime import datetime
from collections.abc import Callable

import dagster
from dagster import Field, Array, MonthlyPartitionsDefinition
from clickhouse_driver import Client
from dags.common import JobOwners
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    DISTRIBUTED_WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_OVERVIEW_METRICS_DAILY_SQL,
    DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    WEB_OVERVIEW_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
    WEB_PATHS_DAILY_SQL,
    DISTRIBUTED_WEB_PATHS_DAILY_SQL,
    WEB_PATHS_INSERT_SQL,
)
from posthog.clickhouse.cluster import ClickhouseCluster


monthly_partitions = MonthlyPartitionsDefinition(
    start_date="2020-01-01",
    end_offset=0,
)

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
    team_ids = config.get("team_ids", [])
    team_ids = [1, 2] if not team_ids else team_ids
    clickhouse_settings = config["clickhouse_settings"]

    if context.partition_key:
        partition_date = datetime.strptime(context.partition_key, "%Y-%m-%d")
        date_start = partition_date.strftime("%Y-%m-01")
        if partition_date.month == 12:
            next_month = partition_date.replace(year=partition_date.year + 1, month=1, day=1)
        else:
            next_month = partition_date.replace(month=partition_date.month + 1, day=1)
        last_day = (next_month).strftime("%Y-%m-%d")
        date_end = last_day

    insert_query = sql_generator(
        date_start=date_start,
        date_end=date_end,
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
    )

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(
        f"Processing partition {context.partition_key if context.partition_key else 'full range'}: {date_start} to {date_end}"
    )
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
        client.execute("DROP TABLE IF EXISTS web_overview_daily SYNC")
        client.execute("DROP TABLE IF EXISTS web_stats_daily SYNC")
        client.execute("DROP TABLE IF EXISTS web_bounces_daily SYNC")
        client.execute("DROP TABLE IF EXISTS web_paths_daily SYNC")

    def create_tables(client: Client):
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name="web_overview_daily"))
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily"))
        client.execute(WEB_PATHS_DAILY_SQL(table_name="web_paths_daily"))

        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_BOUNCES_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_PATHS_DAILY_SQL())

    cluster.map_all_hosts(drop_tables).result()
    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_overview_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_overview_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    partitions_def=monthly_partitions,
    op_tags={"dagster/concurrency_key": "web_analytics", "dagster/max_concurrent": "2"},
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
    name="web_analytics_bounces_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    partitions_def=monthly_partitions,
    op_tags={"dagster/concurrency_key": "web_analytics", "dagster/max_concurrent": "2"},
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
    partitions_def=monthly_partitions,
    op_tags={"dagster/concurrency_key": "web_analytics", "dagster/max_concurrent": "2"},
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


@dagster.asset(
    name="web_analytics_paths_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_paths_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    partitions_def=monthly_partitions,
    op_tags={"dagster/concurrency_key": "web_analytics", "dagster/max_concurrent": "2"},
)
def web_paths_daily(context: dagster.AssetExecutionContext) -> None:
    """
    Simple daily pathnames data with pageviews and unique visitors per path. Intended to use with web_bounces_daily for path-specific analysis.
    """
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_paths_daily",
        sql_generator=WEB_PATHS_INSERT_SQL,
    )


recreate_web_pre_aggregated_data_job = dagster.define_asset_job(
    name="recreate_web_pre_aggregated_data",
    selection=dagster.AssetSelection.groups("web_analytics"),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    partitions_def=monthly_partitions,
    config={"execution": {"config": {"multiprocess": {"max_concurrent": 2}}}},
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

    return [
        dagster.RunRequest(
            run_config={
                "ops": {
                    "web_analytics_overview_daily": {"config": {"team_ids": team_ids}},
                    "web_analytics_bounces_daily": {"config": {"team_ids": team_ids}},
                    "web_analytics_stats_table_daily": {"config": {"team_ids": team_ids}},
                    "web_analytics_paths_daily": {"config": {"team_ids": team_ids}},
                }
            },
        )
    ]
