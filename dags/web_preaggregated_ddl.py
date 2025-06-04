import dagster
import structlog
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

logger = structlog.get_logger(__name__)


@dagster.asset(
    name="web_analytics_preaggregated_hourly_tables",
    group_name="web_analytics",
    description="Creates the hourly tables needed for web analytics preaggregated data with 24h TTL for real-time analytics.",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_preaggregated_hourly_tables(
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def drop_tables(client: Client):
        client.execute("DROP TABLE IF EXISTS web_stats_hourly SYNC")
        client.execute("DROP TABLE IF EXISTS web_bounces_hourly SYNC")
        client.execute("DROP TABLE IF EXISTS web_stats_hourly_staging SYNC")
        client.execute("DROP TABLE IF EXISTS web_bounces_hourly_staging SYNC")

    def create_tables(client: Client):
        client.execute(WEB_STATS_HOURLY_SQL())
        client.execute(WEB_BOUNCES_HOURLY_SQL())

        # Create staging tables with same structure
        client.execute(WEB_STATS_HOURLY_SQL().replace("web_stats_hourly", "web_stats_hourly_staging"))
        client.execute(WEB_BOUNCES_HOURLY_SQL().replace("web_bounces_hourly", "web_bounces_hourly_staging"))

        client.execute(DISTRIBUTED_WEB_STATS_HOURLY_SQL())
        client.execute(DISTRIBUTED_WEB_BOUNCES_HOURLY_SQL())

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
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def create_views(client: Client):
        client.execute(WEB_STATS_COMBINED_VIEW_SQL())
        client.execute(WEB_BOUNCES_COMBINED_VIEW_SQL())

    cluster.map_all_hosts(create_views).result()
    return True


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    retry_policy=web_analytics_retry_policy_def,
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
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
            logger.exception("failed_to_drop_tables", host=client.connection.host, error=str(e))
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
        logger.exception("web_analytics_tables_setup_failed", error=str(e))
        raise dagster.Failure(f"Failed to setup web analytics tables: {str(e)}") from e
