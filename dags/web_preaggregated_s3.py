import os

import dagster
from dagster import DailyPartitionsDefinition, BackfillPolicy

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
    CLICKHOUSE_SETTINGS,
    merge_clickhouse_settings,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    web_analytics_retry_policy_def,
    drop_partitions_in_time_window,
)
from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.models.web_preaggregated.sql import (
    WEB_STATS_DAILY_SQL,
    WEB_BOUNCES_DAILY_SQL,
    WEB_STATS_INSERT_SQL,
    WEB_BOUNCES_INSERT_SQL,
)

max_partitions_per_run = int(os.getenv("DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN", 14))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)
partition_def = DailyPartitionsDefinition(start_date="2024-01-01")


def ensure_s3_table_exists(context: dagster.AssetExecutionContext, table_name: str, sql_generator) -> None:
    create_table_sql = sql_generator(table_name=table_name, storage_policy="s3")
    context.log.info(f"Creating S3-backed table: {table_name}")
    context.log.info(create_table_sql)
    sync_execute(create_table_sql)


def pre_aggregate_web_analytics_s3_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    table_sql_generator,
    insert_sql_generator,
) -> None:
    config = context.op_config
    team_ids = config.get("team_ids", TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED)
    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(f"Getting ready to pre-aggregate S3-backed {table_name} for {context.partition_time_window}")

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    try:
        ensure_s3_table_exists(context, table_name, table_sql_generator)

        drop_partitions_in_time_window(context, table_name, start_datetime, end_datetime, granularity="daily")

        insert_query = insert_sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids if team_ids else TEAM_IDS_WITH_WEB_PREAGGREGATED_ENABLED,
            settings=ch_settings,
            table_name=table_name,
        )

        context.log.info(f"Inserting data into S3-backed table {table_name}")
        context.log.debug(insert_query)
        sync_execute(insert_query)

        context.log.info(f"Successfully materialized S3-backed {table_name}")

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate S3-backed {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_stats_daily_s3_backed",
    group_name="web_analytics_s3",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_stats_daily_s3_backed", "storage": "s3_backed"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "storage": "s3"},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_daily_s3(context: dagster.AssetExecutionContext) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_s3_data(
        context=context,
        table_name="web_stats_daily_s3_backed",
        table_sql_generator=WEB_STATS_DAILY_SQL,
        insert_sql_generator=WEB_STATS_INSERT_SQL,
    )


@dagster.asset(
    name="web_bounces_daily_s3_backed",
    group_name="web_analytics_s3",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_bounces_daily_s3_backed", "storage": "s3_backed"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "storage": "s3"},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_daily_s3(context: dagster.AssetExecutionContext) -> None:
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_s3_data(
        context=context,
        table_name="web_bounces_daily_s3_backed",
        table_sql_generator=WEB_BOUNCES_DAILY_SQL,
        insert_sql_generator=WEB_BOUNCES_INSERT_SQL,
    )


@dagster.job(
    name="web_analytics_s3_materialization",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_s3_job():
    web_stats_daily_s3()
    web_bounces_daily_s3()
