from datetime import datetime, UTC, timedelta
from collections.abc import Callable
import os

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy
import structlog
import chdb
from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
)
from posthog.clickhouse import query_tagging
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
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
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
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
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

        session.query(f"""
            CREATE TABLE {temp_table} ENGINE = Memory AS
            SELECT * FROM s3({get_s3_function_args(source_s3_path)})
        """)

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
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
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
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
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
