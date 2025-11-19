from clickhouse_driver import Client
from dagster import AssetExecutionContext, BackfillPolicy, DailyPartitionsDefinition, asset, define_asset_job

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.git import get_git_commit_short
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3,
    RAW_SESSION_TABLE_BACKFILL_SQL_V3,
)

from dags.common import dagster_tags
from dags.common.common import JobOwners, metabase_debug_query_url

# This is the number of days to backfill in one SQL operation
MAX_PARTITIONS_PER_RUN = 1

# Keep the number of concurrent runs low to avoid overloading ClickHouse and running into the dread "Too many parts".
# This tag needs to also exist in Dagster Cloud (and the local dev dagster.yaml) for the concurrency limit to take effect.
# concurrency:
#   runs:
#     tag_concurrency_limits:
#       - key: 'sessions_backfill_concurrency'
#         limit: 3
#         value:
#           applyLimitPerUniqueValue: true
CONCURRENCY_TAG = {
    "sessions_backfill_concurrency": "sessions_v3",
}

daily_partitions = DailyPartitionsDefinition(
    start_date="2019-01-01",  # this is a year before posthog was founded, so should be early enough even including data imports
    timezone="UTC",
    end_offset=1,  # include today's partition (note that will create a partition with incomplete data, but all our backfills are idempotent so this is ok providing we re-run later)
)

ONE_HOUR_IN_SECONDS = 60 * 60
ONE_GB_IN_BYTES = 1024 * 1024 * 1024

settings = {
    # see this run which took around 2hrs 10min for 1 day https://posthog.dagster.plus/prod-us/runs/0ba8afaa-f3cc-4845-97c5-96731ec8231d?focusedTime=1762898705269&selection=sessions_v3_backfill&logs=step%3Asessions_v3_backfill
    # so to give some margin, allow 4 hours per partition
    "max_execution_time": MAX_PARTITIONS_PER_RUN * 4 * ONE_HOUR_IN_SECONDS,
    "max_memory_usage": 100 * ONE_GB_IN_BYTES,
    "distributed_aggregation_memory_efficient": "1",
}


def get_partition_where_clause(context: AssetExecutionContext, timestamp_field: str) -> str:
    start_incl = context.partition_time_window.start.strftime("%Y-%m-%d")
    end_excl = context.partition_time_window.end.strftime("%Y-%m-%d")

    # it's ok that we use inclusive equality for both comparisons here, adding events to this table is idempotent
    # so if an event did get added twice on the exact boundary, the data would still be correct
    return f"'{start_incl}' <= {timestamp_field} AND {timestamp_field} <= '{end_excl}'"


@asset(
    partitions_def=daily_partitions,
    name="sessions_v3_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)
def sessions_v3_backfill(context: AssetExecutionContext) -> None:
    where_clause = get_partition_where_clause(context, timestamp_field="timestamp")

    # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
    # as long as the backfill has run at least once for each partition, the data will be correct
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL_V3(where=where_clause, use_sharded_source=True)

    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"
    context.log.info(
        f"Running backfill for {partition_range_str} (where='{where_clause}') using commit {get_git_commit_short() or 'unknown'} "
    )
    context.log.info(backfill_sql)
    if debug_url := metabase_debug_query_url(context.run_id):
        context.log.info(f"Debug query: {debug_url}")

    cluster = get_cluster()
    tags = dagster_tags(context)

    def backfill_per_shard(client: Client):
        with tags_context(kind="dagster", dagster=tags):
            sync_execute(backfill_sql, settings=settings, sync_client=client)

    cluster.map_one_host_per_shard(backfill_per_shard).result()

    context.log.info(f"Successfully backfilled sessions_v3 for {partition_range_str}")


@asset(
    partitions_def=daily_partitions,
    name="sessions_v3_replay_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)
def sessions_v3_backfill_replay(context: AssetExecutionContext) -> None:
    where_clause = get_partition_where_clause(context, timestamp_field="min_first_timestamp")

    # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
    # as long as the backfill has run at least once for each partition, the data will be correct
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3(where=where_clause, use_sharded_source=True)

    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"
    context.log.info(
        f"Running backfill for {partition_range_str} (where='{where_clause}') using commit {get_git_commit_short() or 'unknown'} "
    )
    context.log.info(backfill_sql)
    if debug_url := metabase_debug_query_url(context.run_id):
        context.log.info(f"Debug query: {debug_url}")

    cluster = get_cluster()
    tags = dagster_tags(context)

    def backfill_per_shard(client: Client):
        with tags_context(kind="dagster", dagster=tags):
            sync_execute(backfill_sql, workload=Workload.OFFLINE, settings=settings, sync_client=client)

    cluster.map_one_host_per_shard(backfill_per_shard).result()

    context.log.info(f"Successfully backfilled sessions_v3 for {partition_range_str}")


sessions_backfill_job = define_asset_job(
    name="sessions_v3_backfill_job",
    selection=["sessions_v3_backfill", "sessions_v3_replay_backfill"],
    partitions_def=daily_partitions,
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)
