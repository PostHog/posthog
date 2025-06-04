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
    WEB_BOUNCES_EXPORT_SQL,
    WEB_STATS_EXPORT_SQL,
)
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG
from posthog.settings.object_storage import (
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER,
)


WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - if empty we will process for teams [1,2] only",
    ),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=1200,max_bytes_before_external_group_by=21474836480,distributed_aggregation_memory_efficient=1,s3_truncate_on_insert=1",
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
    )

    # We intentionally log the query to make it easier to debug using the UI
    context.log.info(insert_query)

    sync_execute(insert_query)


def export_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    export_prefix: str,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", [1, 2])
    clickhouse_settings = config["clickhouse_settings"]

    if DEBUG:
        s3_path = f"{OBJECT_STORAGE_ENDPOINT}/{OBJECT_STORAGE_BUCKET}/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{export_prefix}.native"
    else:
        s3_path = f"https://{OBJECT_STORAGE_BUCKET}.s3.amazonaws.com/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{export_prefix}.native"

    export_query = sql_generator(
        date_start="2020-01-01",
        date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
        team_ids=team_ids,
        settings=clickhouse_settings,
        table_name=table_name,
        s3_path=s3_path,
    )

    context.log.info(export_query)

    sync_execute(export_query)

    context.log.info(f"Successfully exported {table_name} to S3: {s3_path}")


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


@dagster.asset(
    name="web_analytics_stats_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_stats_table_daily"],
    metadata={"export_file": "web_stats_daily_export.native"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_daily_export(context: dagster.AssetExecutionContext):
    """
    Exports web_stats_daily data directly to S3 using ClickHouse's native S3 export.
    """
    return export_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_EXPORT_SQL,
        export_prefix="web_stats_daily_export",
    )


@dagster.asset(
    name="web_analytics_bounces_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_bounces_daily"],
    metadata={"export_file": "web_bounces_daily_export.native"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_daily_export(context: dagster.AssetExecutionContext):
    """
    Exports web_bounces_daily data directly to S3 using ClickHouse's native S3 export.
    """
    return export_web_analytics_data(
        context=context,
        table_name="web_bounces_daily",
        sql_generator=WEB_BOUNCES_EXPORT_SQL,
        export_prefix="web_bounces_daily_export",
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
                "web_analytics_stats_export": {"config": {"team_ids": team_ids}},
                "web_analytics_bounces_export": {"config": {"team_ids": team_ids}},
            }
        },
    )
