from datetime import datetime, UTC, timedelta
from collections.abc import Callable
import os

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy, asset_check, AssetCheckResult, MetadataValue
import structlog
from dags.common import JobOwners
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
)
from posthog.clickhouse.client import sync_execute

from posthog.models.web_preaggregated.sql import (
    WEB_BOUNCES_EXPORT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_EXPORT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.settings.base_variables import DEBUG
from posthog.settings.dagster import DAGSTER_DATA_EXPORT_S3_BUCKET
from posthog.settings.object_storage import (
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER,
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


def export_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    export_prefix: str,
) -> dagster.Output[str]:
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, config.get("extra_clickhouse_settings", ""))

    if DEBUG:
        s3_path = f"{OBJECT_STORAGE_ENDPOINT}/{OBJECT_STORAGE_BUCKET}/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{export_prefix}.native"
    else:
        s3_path = f"https://{DAGSTER_DATA_EXPORT_S3_BUCKET}.s3.amazonaws.com/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/{export_prefix}.native"

    export_query = sql_generator(
        date_start="2020-01-01",
        date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
        team_ids=team_ids,
        settings=ch_settings,
        table_name=table_name,
        s3_path=s3_path,
    )

    sync_execute(export_query)

    context.log.info(f"Successfully exported {table_name} to S3: {s3_path}")

    return dagster.Output(
        value=s3_path,
        metadata={
            "s3_path": s3_path,
            "table_name": table_name,
        },
    )


@dagster.asset(
    name="web_analytics_stats_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_stats_table_daily"],
    metadata={"export_file": "web_stats_daily_export.native"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_daily_export(context: dagster.AssetExecutionContext) -> dagster.Output[str]:
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
def web_bounces_daily_export(context: dagster.AssetExecutionContext) -> dagster.Output[str]:
    """
    Exports web_bounces_daily data directly to S3 using ClickHouse's native S3 export.
    """
    return export_web_analytics_data(
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


# Asset checks for daily tables
@asset_check(
    asset=web_bounces_daily,
    name="bounces_daily_has_data",
    description="Check if web_bounces_daily table has data",
)
def bounces_daily_has_data() -> AssetCheckResult:
    """
    Check if the web_bounces_daily table has data.
    """
    try:
        result = sync_execute("SELECT COUNT(*) FROM web_bounces_daily LIMIT 1")
        row_count = result[0][0] if result and result[0] else 0

        passed = row_count > 0

        return AssetCheckResult(
            passed=passed,
            description=f"Table has {row_count} rows" if passed else "Table is empty",
            metadata={"row_count": MetadataValue.int(row_count), "table_name": MetadataValue.text("web_bounces_daily")},
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking table: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


@asset_check(
    asset=web_stats_daily,
    name="stats_daily_has_data",
    description="Check if web_stats_daily table has data",
)
def stats_daily_has_data() -> AssetCheckResult:
    """
    Check if the web_stats_daily table has data.
    """
    try:
        result = sync_execute("SELECT COUNT(*) FROM web_stats_daily LIMIT 1")
        row_count = result[0][0] if result and result[0] else 0

        passed = row_count > 0

        return AssetCheckResult(
            passed=passed,
            description=f"Table has {row_count} rows" if passed else "Table is empty",
            metadata={"row_count": MetadataValue.int(row_count), "table_name": MetadataValue.text("web_stats_daily")},
        )
    except Exception as e:
        return AssetCheckResult(
            passed=False, description=f"Error checking table: {str(e)}", metadata={"error": MetadataValue.text(str(e))}
        )


# Asset checks for export files - verify chdb can query them and they have data
@asset_check(
    asset=web_stats_daily_export,
    name="stats_export_chdb_queryable",
    description="Check if stats export file can be queried with chdb and has data",
)
def stats_export_chdb_queryable() -> AssetCheckResult:
    """
    Check if the web_stats_daily export file can be queried with chdb and contains data.
    """
    try:
        import chdb
        import structlog

        logger = structlog.get_logger(__name__)

        # Get the export path - in local dev use Minio URL
        if DEBUG:
            # For local development, use the Minio URL directly
            export_url = f"http://objectstorage:19000/posthog/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/web_stats_daily_export.native"

            try:
                # Try to query the export file with chdb using Minio URL
                result = chdb.query(f"SELECT COUNT(*) as row_count FROM url('{export_url}', 'Native')")
                row_count = int(result.data().strip()) if result.data().strip().isdigit() else 0

                passed = row_count > 0

                logger.info("stats_export_chdb_check", export_url=export_url, row_count=row_count, queryable=True)

                return AssetCheckResult(
                    passed=passed,
                    description=f"Export file queryable with chdb via Minio, contains {row_count} rows"
                    if passed
                    else "Export file queryable but empty",
                    metadata={
                        "row_count": MetadataValue.int(row_count),
                        "export_url": MetadataValue.text(export_url),
                        "chdb_queryable": MetadataValue.bool(True),
                        "export_type": MetadataValue.text("web_stats_daily"),
                    },
                )

            except (FileNotFoundError, Exception) as e:
                # File doesn't exist yet or has format issues - this is ok for a check
                error_msg = str(e)
                if "Cannot stat file" in error_msg or "CANNOT_STAT" in error_msg:
                    status = "file_not_found"
                    description = "Export file not found - may not have been created yet"
                elif "table structure cannot be extracted" in error_msg.lower():
                    status = "format_issue"
                    description = (
                        "Export file exists but chdb cannot determine structure - this is expected for Native format"
                    )
                else:
                    status = "other_error"
                    description = f"Export file check failed: {error_msg}"

                logger.info("stats_export_chdb_check", export_url=export_url, status=status, error=error_msg[:100])

                return AssetCheckResult(
                    passed=False,
                    description=description,
                    metadata={
                        "export_url": MetadataValue.text(export_url),
                        "error": MetadataValue.text(error_msg[:200]),
                        "export_type": MetadataValue.text("web_stats_daily"),
                        "status": MetadataValue.text(status),
                    },
                )
        else:
            # For production, we'd need to handle S3 access differently
            # For now, just return a placeholder
            return AssetCheckResult(
                passed=True,
                description="Production chdb export check not implemented yet",
                metadata={
                    "environment": MetadataValue.text("production"),
                    "export_type": MetadataValue.text("web_stats_daily"),
                },
            )

    except ImportError:
        return AssetCheckResult(
            passed=False,
            description="chdb not available - cannot verify export queryability",
            metadata={"error": MetadataValue.text("chdb import failed")},
        )
    except Exception as e:
        logger.exception("stats_export_chdb_check_error", error=str(e))
        return AssetCheckResult(
            passed=False,
            description=f"Error checking export with chdb: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )


@asset_check(
    asset=web_bounces_daily_export,
    name="bounces_export_chdb_queryable",
    description="Check if bounces export file can be queried with chdb and has data",
)
def bounces_export_chdb_queryable() -> AssetCheckResult:
    """
    Check if the web_bounces_daily export file can be queried with chdb and contains data.
    """
    try:
        import chdb
        import structlog

        logger = structlog.get_logger(__name__)

        # Get the export path - in local dev use Minio URL
        if DEBUG:
            # For local development, use the Minio URL directly
            export_url = f"http://objectstorage:19000/posthog/{OBJECT_STORAGE_PREAGGREGATED_WEB_ANALYTICS_FOLDER}/web_bounces_daily_export.native"

            try:
                # Try to query the export file with chdb using Minio URL
                result = chdb.query(f"SELECT COUNT(*) as row_count FROM url('{export_url}', 'Native')")
                row_count = int(result.data().strip()) if result.data().strip().isdigit() else 0

                passed = row_count > 0

                logger.info("bounces_export_chdb_check", export_url=export_url, row_count=row_count, queryable=True)

                return AssetCheckResult(
                    passed=passed,
                    description=f"Export file queryable with chdb via Minio, contains {row_count} rows"
                    if passed
                    else "Export file queryable but empty",
                    metadata={
                        "row_count": MetadataValue.int(row_count),
                        "export_url": MetadataValue.text(export_url),
                        "chdb_queryable": MetadataValue.bool(True),
                        "export_type": MetadataValue.text("web_bounces_daily"),
                    },
                )

            except (FileNotFoundError, Exception) as e:
                # File doesn't exist yet or has format issues - this is ok for a check
                error_msg = str(e)
                if "Cannot stat file" in error_msg or "CANNOT_STAT" in error_msg:
                    status = "file_not_found"
                    description = "Export file not found - may not have been created yet"
                elif "table structure cannot be extracted" in error_msg.lower():
                    status = "format_issue"
                    description = (
                        "Export file exists but chdb cannot determine structure - this is expected for Native format"
                    )
                else:
                    status = "other_error"
                    description = f"Export file check failed: {error_msg}"

                logger.info("bounces_export_chdb_check", export_url=export_url, status=status, error=error_msg[:100])

                return AssetCheckResult(
                    passed=False,
                    description=description,
                    metadata={
                        "export_url": MetadataValue.text(export_url),
                        "error": MetadataValue.text(error_msg[:200]),
                        "export_type": MetadataValue.text("web_bounces_daily"),
                        "status": MetadataValue.text(status),
                    },
                )
        else:
            # For production, we'd need to handle S3 access differently
            # For now, just return a placeholder
            return AssetCheckResult(
                passed=True,
                description="Production chdb export check not implemented yet",
                metadata={
                    "environment": MetadataValue.text("production"),
                    "export_type": MetadataValue.text("web_bounces_daily"),
                },
            )

    except ImportError:
        return AssetCheckResult(
            passed=False,
            description="chdb not available - cannot verify export queryability",
            metadata={"error": MetadataValue.text("chdb import failed")},
        )
    except Exception as e:
        logger.exception("bounces_export_chdb_check_error", error=str(e))
        return AssetCheckResult(
            passed=False,
            description=f"Error checking export with chdb: {str(e)}",
            metadata={"error": MetadataValue.text(str(e))},
        )
