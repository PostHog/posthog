from datetime import datetime, UTC, timedelta
from collections.abc import Callable
import os

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy, AssetCheckResult, asset_check
import structlog
import chdb
from dags.common import JobOwners
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
    format_clickhouse_settings,
)
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_EXPORT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_EXPORT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.hogql.database.schema.web_analytics_s3 import (
    get_s3_function_args,
)
from posthog.settings.base_variables import DEBUG
from posthog.settings.object_storage import (
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET,
)


logger = structlog.get_logger(__name__)

# From my tests, 14 (two weeks) is a sane value for production.
# But locally we can run more partitions per run to speed up testing (e.g: 3000 to materialize everything on a single run)
max_partitions_per_run = int(os.getenv("DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN", 14))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)

partition_def = DailyPartitionsDefinition(start_date="2020-01-01")


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
) -> None:
    """
    Pre-aggregate web analytics data for a given table and date range.

    Args:
        context: Dagster execution context
        table_name: Target table name (web_stats_daily or web_bounces_daily)
        sql_generator: Function to generate SQL query
    """
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(f"Getting ready to pre-aggregate {table_name} for {context.partition_time_window}")

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    try:
        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids if team_ids else TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
            settings=ch_settings,
            table_name=table_name,
        )

        # Intentionally log query details for debugging
        context.log.info(insert_query)

        sync_execute(insert_query)

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_analytics_bounces_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_daily(
    context: dagster.AssetExecutionContext,
) -> None:
    """
    Daily bounce rate data for web analytics.

    Aggregates bounce rate, session duration, and other session-level metrics
    by various dimensions (UTM parameters, geography, device info, etc.).
    """
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_bounces_daily",
        sql_generator=WEB_BOUNCES_INSERT_SQL,
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_stats_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_daily(context: dagster.AssetExecutionContext) -> None:
    """
    Aggregated dimensional data with pageviews and unique user counts.

    Aggregates pageview counts, unique visitors, and unique sessions
    by various dimensions (pathnames, UTM parameters, geography, device info, etc.).
    """
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


def export_web_analytics_data_by_team(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    export_prefix: str,
) -> dagster.Output[list]:
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, config.get("extra_clickhouse_settings", ""))

    successfully_exported_paths = []
    failed_team_ids = []

    for team_id in team_ids:
        if DEBUG:
            team_s3_path = f"{OBJECT_STORAGE_ENDPOINT}/{OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET}/{export_prefix}/{team_id}/data.native"
        else:
            team_s3_path = f"https://{OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET}.s3.amazonaws.com/{export_prefix}/{team_id}/data.native"

        export_query = sql_generator(
            date_start="2020-01-01",
            date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
            team_ids=[team_id],
            settings=ch_settings,
            table_name=table_name,
            s3_path=team_s3_path,
        )

        try:
            context.log.info(f"Exporting {table_name} for team {team_id} to: {team_s3_path}")
            sync_execute(export_query)

            successfully_exported_paths.append(team_s3_path)
            context.log.info(f"Successfully exported {table_name} for team {team_id} to: {team_s3_path}")

        except Exception as e:
            context.log.exception(f"Failed to export {table_name} for team {team_id}: {str(e)}")
            failed_team_ids.append(team_id)

    return dagster.Output(
        value=successfully_exported_paths,
        metadata={
            "team_count": len(successfully_exported_paths),
            "exported_paths": successfully_exported_paths,
            "failed_team_ids": failed_team_ids,
        },
    )


def partition_web_analytics_data_by_team(
    context: dagster.AssetExecutionContext,
    source_s3_path: str,
    structure: str,
) -> dagster.Output[list]:
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)

    successfully_team_ids = []
    failed_team_ids = []

    session = chdb.session.Session()
    try:
        temp_db = f"temp_analytics_{context.run_id.replace('-', '_')}"
        session.query(f"CREATE DATABASE IF NOT EXISTS {temp_db} ENGINE = Atomic")

        temp_table = f"{temp_db}.source_data"

        session.query(
            f"""
            CREATE TABLE {temp_table} ENGINE = Memory AS
            SELECT * FROM s3({get_s3_function_args(source_s3_path)})
        """
        )

        context.log.info(f"Loaded source data into temporary table {temp_table}")

        for team_id in team_ids:
            team_s3_path = f"{source_s3_path.replace('.native', '')}/{team_id}/data.native"

            partition_query = f"""
            INSERT INTO FUNCTION s3({get_s3_function_args(team_s3_path)}, '{structure}')
            SELECT *
            FROM {temp_table}
            WHERE team_id = {team_id}
            SETTINGS s3_truncate_on_insert=true
            """

            try:
                context.log.info(f"Partitioning data for team {team_id}")
                session.query(partition_query)

                successfully_team_ids.append(team_s3_path)
                context.log.info(f"Successfully partitioned data for team {team_id} to: {team_s3_path}")

            except Exception as e:
                context.log.exception(f"Failed to partition data for team {team_id}: {str(e)}")
                failed_team_ids.append(team_id)

    finally:
        session.cleanup()

    return dagster.Output(
        value=successfully_team_ids,
        metadata={
            "team_count": len(successfully_team_ids),
            "team_ids": successfully_team_ids,
            "failed_team_ids": failed_team_ids,
        },
    )


@dagster.asset(
    name="web_analytics_stats_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_stats_table_daily"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_daily_export(context: dagster.AssetExecutionContext) -> dagster.Output[list]:
    """
    Exports web_stats_daily data directly to S3 partitioned by team using ClickHouse's native S3 export.
    """
    return export_web_analytics_data_by_team(
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
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_daily_export(context: dagster.AssetExecutionContext) -> dagster.Output[list]:
    """
    Exports web_bounces_daily data directly to S3 partitioned by team using ClickHouse's native S3 export.
    """
    return export_web_analytics_data_by_team(
        context=context,
        table_name="web_bounces_daily",
        sql_generator=WEB_BOUNCES_EXPORT_SQL,
        export_prefix="web_bounces_daily_export",
    )


# Daily incremental job with asset-level concurrency control
web_pre_aggregate_daily_job = dagster.define_asset_job(
    name="web_analytics_daily_job",
    selection=["web_analytics_bounces_daily", "web_analytics_stats_table_daily"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        # The instance level config limits the job concurrency on the run queue
        # https://github.com/PostHog/charts/blob/chore/dagster-config/config/dagster/prod-us.yaml#L179-L181
    },
    # This limit the concurrency of the assets inside the job, so they run sequentially
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


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job=web_pre_aggregate_daily_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition.
    The usage of pre-aggregated tables is controlled by a query modifier AND is behind a feature flag.
    """

    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "web_analytics_bounces_daily": {"config": {"team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED}},
                "web_analytics_stats_table_daily": {"config": {"team_ids": TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED}},
            }
        },
    )


@dagster.asset(
    name="web_analytics_active_teams_90d",
    group_name="web_analytics",
    deps=["web_analytics_stats_table_daily"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_analytics_active_teams_90d(context: dagster.AssetExecutionContext) -> dagster.Output[list]:
    """
    Fetches teams with pageview activity in the last 90 days from pre-aggregated tables.

    Returns a list of team data with pageview counts that can be used by other assets.
    """
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, "")

    # Calculate date range for last 90 days
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=90)

    date_start = start_date.strftime("%Y-%m-%d")
    date_end = end_date.strftime("%Y-%m-%d")

    query = f"""
    SELECT
        team_id,
        sumMerge(pageviews_count_state) as total_pageviews
    FROM web_stats_daily
    WHERE period_bucket >= toDateTime('{date_start}', 'UTC')
        AND period_bucket < toDateTime('{date_end}', 'UTC')
    GROUP BY team_id
    HAVING total_pageviews > 0
    ORDER BY total_pageviews DESC
    SETTINGS {format_clickhouse_settings(ch_settings)}
    """

    try:
        context.log.info(f"Querying active teams for date range: {date_start} to {date_end}")
        context.log.info(f"Query: {query}")

        result = sync_execute(query)

        active_teams = []
        total_teams = 0
        total_pageviews = 0

        for row in result:
            team_id, pageviews = int(row[0]), int(row[1])
            active_teams.append({"team_id": team_id, "pageviews_90d": pageviews})
            total_teams += 1
            total_pageviews += pageviews

        context.log.info(f"Found {total_teams} active teams with {total_pageviews:,} total pageviews in last 90 days")

        # Extract just the team IDs for easy consumption by other assets
        team_ids = [team["team_id"] for team in active_teams]

        return dagster.Output(
            value=team_ids,
            metadata={
                "total_teams": dagster.MetadataValue.int(total_teams),
                "total_pageviews": dagster.MetadataValue.int(total_pageviews),
                "date_range": dagster.MetadataValue.text(f"{date_start} to {date_end}"),
                "team_details": dagster.MetadataValue.json(active_teams[:20]),  # Show top 20 teams
                "query": dagster.MetadataValue.text(query),
            },
        )

    except Exception as e:
        raise dagster.Failure(f"Failed to fetch active teams: {str(e)}") from e


@asset_check(
    asset="web_analytics_active_teams_90d",
    name="web_stats_daily_query_with_active_teams",
    description="Verify web_stats_daily table can be queried successfully with teams from active teams list",
)
def web_stats_daily_query_with_active_teams(
    context: dagster.AssetCheckExecutionContext, web_analytics_active_teams_90d: list
) -> AssetCheckResult:
    """
    Asset check to verify that web_stats_daily table works with the active teams list.
    """
    if not web_analytics_active_teams_90d:
        return AssetCheckResult(
            passed=False,
            description="No active teams found to test query with",
            metadata={"team_count": dagster.MetadataValue.int(0)},
        )

    # Test with a subset of teams to avoid timeout
    test_teams = web_analytics_active_teams_90d[:10]
    team_ids_str = ",".join(str(team_id) for team_id in test_teams)

    # Test query for last 7 days
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=7)
    date_start = start_date.strftime("%Y-%m-%d")
    date_end = end_date.strftime("%Y-%m-%d")

    test_query = f"""
    SELECT
        team_id,
        count(*) as row_count,
        sumMerge(pageviews_count_state) as total_pageviews
    FROM web_stats_daily
    WHERE team_id IN ({team_ids_str})
        AND period_bucket >= toDateTime('{date_start}', 'UTC')
        AND period_bucket < toDateTime('{date_end}', 'UTC')
    GROUP BY team_id
    ORDER BY team_id
    LIMIT 100
    """

    try:
        context.log.info(f"Testing web_stats_daily query with {len(test_teams)} teams")
        result = sync_execute(test_query)

        teams_with_data = len(result)
        total_rows = sum(int(row[1]) for row in result)
        total_pageviews = sum(int(row[2]) for row in result)

        if teams_with_data > 0:
            return AssetCheckResult(
                passed=True,
                description=f"Successfully queried web_stats_daily with {teams_with_data} teams returning {total_rows} rows",
                metadata={
                    "tested_teams": dagster.MetadataValue.int(len(test_teams)),
                    "teams_with_data": dagster.MetadataValue.int(teams_with_data),
                    "total_rows": dagster.MetadataValue.int(total_rows),
                    "total_pageviews": dagster.MetadataValue.int(total_pageviews),
                    "date_range": dagster.MetadataValue.text(f"{date_start} to {date_end}"),
                },
            )
        else:
            return AssetCheckResult(
                passed=False,
                description=f"Query succeeded but no data found for {len(test_teams)} test teams",
                metadata={
                    "tested_teams": dagster.MetadataValue.int(len(test_teams)),
                    "teams_with_data": dagster.MetadataValue.int(0),
                },
            )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Failed to query web_stats_daily table: {str(e)}",
            metadata={
                "error": dagster.MetadataValue.text(str(e)),
                "tested_teams": dagster.MetadataValue.int(len(test_teams)),
            },
        )


@asset_check(
    asset="web_analytics_active_teams_90d",
    name="web_bounces_daily_query_with_active_teams",
    description="Verify web_bounces_daily table can be queried successfully with teams from active teams list",
)
def web_bounces_daily_query_with_active_teams(
    context: dagster.AssetCheckExecutionContext, web_analytics_active_teams_90d: list
) -> AssetCheckResult:
    """
    Asset check to verify that web_bounces_daily table works with the active teams list.
    """
    if not web_analytics_active_teams_90d:
        return AssetCheckResult(
            passed=False,
            description="No active teams found to test query with",
            metadata={"team_count": dagster.MetadataValue.int(0)},
        )

    # Test with a subset of teams to avoid timeout
    test_teams = web_analytics_active_teams_90d[:10]
    team_ids_str = ",".join(str(team_id) for team_id in test_teams)

    # Test query for last 7 days
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=7)
    date_start = start_date.strftime("%Y-%m-%d")
    date_end = end_date.strftime("%Y-%m-%d")

    test_query = f"""
    SELECT
        team_id,
        count(*) as row_count,
        sumMerge(bounces_count_state) as total_bounces,
        uniqMerge(sessions_uniq_state) as unique_sessions
    FROM web_bounces_daily
    WHERE team_id IN ({team_ids_str})
        AND period_bucket >= toDateTime('{date_start}', 'UTC')
        AND period_bucket < toDateTime('{date_end}', 'UTC')
    GROUP BY team_id
    ORDER BY team_id
    LIMIT 100
    """

    try:
        context.log.info(f"Testing web_bounces_daily query with {len(test_teams)} teams")
        result = sync_execute(test_query)

        teams_with_data = len(result)
        total_rows = sum(int(row[1]) for row in result)
        total_bounces = sum(int(row[2]) for row in result)
        total_sessions = sum(int(row[3]) for row in result)

        if teams_with_data > 0:
            return AssetCheckResult(
                passed=True,
                description=f"Successfully queried web_bounces_daily with {teams_with_data} teams returning {total_rows} rows",
                metadata={
                    "tested_teams": dagster.MetadataValue.int(len(test_teams)),
                    "teams_with_data": dagster.MetadataValue.int(teams_with_data),
                    "total_rows": dagster.MetadataValue.int(total_rows),
                    "total_bounces": dagster.MetadataValue.int(total_bounces),
                    "total_sessions": dagster.MetadataValue.int(total_sessions),
                    "date_range": dagster.MetadataValue.text(f"{date_start} to {date_end}"),
                },
            )
        else:
            return AssetCheckResult(
                passed=False,
                description=f"Query succeeded but no data found for {len(test_teams)} test teams",
                metadata={
                    "tested_teams": dagster.MetadataValue.int(len(test_teams)),
                    "teams_with_data": dagster.MetadataValue.int(0),
                },
            )

    except Exception as e:
        return AssetCheckResult(
            passed=False,
            description=f"Failed to query web_bounces_daily table: {str(e)}",
            metadata={
                "error": dagster.MetadataValue.text(str(e)),
                "tested_teams": dagster.MetadataValue.int(len(test_teams)),
            },
        )
