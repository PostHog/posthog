import dagster
from dags.common import JobOwners
from posthog.clickhouse.cluster import ClickhouseCluster
from clickhouse_driver import Client
from dagster import asset_check, AssetCheckResult, MetadataValue

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


# Asset checks for DDL - verify tables and views exist
@asset_check(
    asset=web_analytics_preaggregated_tables,
    name="daily_tables_exist",
    description="Check if daily pre-aggregated tables were created",
)
def daily_tables_exist() -> AssetCheckResult:
    """
    Check if daily pre-aggregated tables exist and have proper structure.
    """
    try:
        from posthog.clickhouse.client import sync_execute

        # Check if tables exist
        tables_result = sync_execute("SHOW TABLES LIKE '%bounces_daily%' OR LIKE '%stats_daily%'")
        table_names = [row[0] for row in tables_result]

        expected_tables = ["web_bounces_daily", "web_stats_daily"]
        missing_tables = [table for table in expected_tables if table not in table_names]

        passed = len(missing_tables) == 0

        return AssetCheckResult(
            passed=passed,
            description=f"Found tables: {table_names}" if passed else f"Missing tables: {missing_tables}",
            metadata={
                "found_tables": MetadataValue.json(table_names),
                "expected_tables": MetadataValue.json(expected_tables),
                "missing_tables": MetadataValue.json(missing_tables),
            },
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking tables: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


@asset_check(
    asset=web_analytics_preaggregated_hourly_tables,
    name="hourly_tables_exist",
    description="Check if hourly pre-aggregated tables were created",
)
def hourly_tables_exist() -> AssetCheckResult:
    """
    Check if hourly pre-aggregated tables exist and have proper structure.
    """
    try:
        from posthog.clickhouse.client import sync_execute

        # Check if tables exist
        tables_result = sync_execute("SHOW TABLES LIKE '%bounces_hourly%' OR LIKE '%stats_hourly%'")
        table_names = [row[0] for row in tables_result]

        expected_tables = [
            "web_bounces_hourly",
            "web_stats_hourly",
            "web_bounces_hourly_staging",
            "web_stats_hourly_staging",
        ]
        missing_tables = [table for table in expected_tables if table not in table_names]

        passed = len(missing_tables) == 0

        return AssetCheckResult(
            passed=passed,
            description=f"Found {len(table_names)} tables" if passed else f"Missing {len(missing_tables)} tables",
            metadata={
                "found_tables": MetadataValue.json(table_names),
                "expected_tables": MetadataValue.json(expected_tables),
                "missing_tables": MetadataValue.json(missing_tables),
            },
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking tables: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


@asset_check(
    asset=web_analytics_combined_views,
    name="combined_views_exist",
    description="Check if combined views were created and are queryable",
)
def combined_views_exist() -> AssetCheckResult:
    """
    Check if combined views exist and are queryable.
    """
    try:
        from posthog.clickhouse.client import sync_execute

        # Check if views exist
        views_result = sync_execute("SHOW TABLES LIKE '%combined%'")
        view_names = [row[0] for row in views_result]

        expected_views = ["web_bounces_combined", "web_stats_combined"]
        missing_views = [view for view in expected_views if view not in view_names]

        # Test if views are queryable
        queryable_views = []
        for view in expected_views:
            if view in view_names:
                try:
                    sync_execute(f"SELECT 1 FROM {view} LIMIT 1")
                    queryable_views.append(view)
                except Exception:
                    pass

        passed = len(missing_views) == 0 and len(queryable_views) == len(expected_views)

        return AssetCheckResult(
            passed=passed,
            description=f"Found {len(queryable_views)}/{len(expected_views)} working views"
            if passed
            else f"Issues with views: {missing_views}",
            metadata={
                "found_views": MetadataValue.json(view_names),
                "expected_views": MetadataValue.json(expected_views),
                "queryable_views": MetadataValue.json(queryable_views),
                "missing_views": MetadataValue.json(missing_views),
            },
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking views: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )
