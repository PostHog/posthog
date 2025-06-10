import dagster
from dags.common import JobOwners
from posthog.clickhouse.cluster import ClickhouseCluster
from clickhouse_driver import Client

from posthog.models.web_preaggregated.sql import (
    DISTRIBUTED_WEB_BOUNCES_DAILY_SQL,
    DISTRIBUTED_WEB_BOUNCES_HOURLY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_HOURLY_SQL,
    WEB_BOUNCES_COMBINED_VIEW_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_BOUNCES_HOURLY_SQL,
    WEB_STATS_COMBINED_VIEW_SQL,
    WEB_STATS_DAILY_SQL,
    WEB_STATS_HOURLY_SQL,
)
from dags.web_preaggregated_utils import web_analytics_retry_policy_def


def execute_with_logging(client: Client, sql: str, context: dagster.AssetExecutionContext):
    context.log.info(sql)
    return client.execute(sql)


@dagster.asset(
    name="web_analytics_preaggregated_hourly_tables",
    group_name="web_analytics",
    description="Creates the hourly tables needed for web analytics preaggregated data with 24h TTL for real-time analytics.",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_preaggregated_hourly_tables(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def drop_tables(client: Client):
        execute_with_logging(client, "DROP TABLE IF EXISTS web_stats_hourly SYNC", context)
        execute_with_logging(client, "DROP TABLE IF EXISTS web_bounces_hourly SYNC", context)
        execute_with_logging(client, "DROP TABLE IF EXISTS web_stats_hourly_staging SYNC", context)
        execute_with_logging(client, "DROP TABLE IF EXISTS web_bounces_hourly_staging SYNC", context)

    def create_tables(client: Client):
        execute_with_logging(client, WEB_STATS_HOURLY_SQL(), context)
        execute_with_logging(client, WEB_BOUNCES_HOURLY_SQL(), context)

        # Create staging tables with same structure
        execute_with_logging(
            client, WEB_STATS_HOURLY_SQL().replace("web_stats_hourly", "web_stats_hourly_staging"), context
        )
        execute_with_logging(
            client, WEB_BOUNCES_HOURLY_SQL().replace("web_bounces_hourly", "web_bounces_hourly_staging"), context
        )

        execute_with_logging(client, DISTRIBUTED_WEB_STATS_HOURLY_SQL(), context)
        execute_with_logging(client, DISTRIBUTED_WEB_BOUNCES_HOURLY_SQL(), context)

    cluster.map_all_hosts(drop_tables).result()
    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_combined_views",
    group_name="web_analytics",
    description="Creates combined views that automatically merge daily and hourly data using toStartOfDay(now()) boundary.",
    deps=["web_analytics_preaggregated_tables", "web_analytics_preaggregated_hourly_tables"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_combined_views(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def drop_views(client: Client):
        execute_with_logging(client, "DROP VIEW IF EXISTS web_stats_combined SYNC", context)
        execute_with_logging(client, "DROP VIEW IF EXISTS web_bounces_combined SYNC", context)

    def create_views(client: Client):
        execute_with_logging(client, WEB_STATS_COMBINED_VIEW_SQL(), context)
        execute_with_logging(client, WEB_BOUNCES_COMBINED_VIEW_SQL(), context)

    cluster.map_all_hosts(drop_views).result()
    cluster.map_all_hosts(create_views).result()
    return True


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    retry_policy=web_analytics_retry_policy_def,
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_preaggregated_tables(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    """
    Create web analytics pre-aggregated tables on all ClickHouse hosts.

    This asset creates both local and distributed tables for web analytics.
    """

    def drop_tables(client: Client):
        try:
            execute_with_logging(client, "DROP TABLE IF EXISTS web_stats_daily SYNC", context)
            execute_with_logging(client, "DROP TABLE IF EXISTS web_bounces_daily SYNC", context)
        except Exception as e:
            raise dagster.Failure(f"Failed to drop tables: {str(e)}") from e

    def create_tables(client: Client):
        execute_with_logging(client, WEB_STATS_DAILY_SQL(table_name="web_stats_daily"), context)
        execute_with_logging(client, WEB_BOUNCES_DAILY_SQL(table_name="web_bounces_daily"), context)

        execute_with_logging(client, DISTRIBUTED_WEB_STATS_DAILY_SQL(), context)
        execute_with_logging(client, DISTRIBUTED_WEB_BOUNCES_DAILY_SQL(), context)

    try:
        cluster.map_all_hosts(drop_tables).result()
        cluster.map_all_hosts(create_tables).result()
        return True
    except Exception as e:
        raise dagster.Failure(f"Failed to setup web analytics tables: {str(e)}") from e
