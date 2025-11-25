import time
from collections.abc import Callable
from typing import Any, Optional

from clickhouse_driver import Client
from dagster import AssetExecutionContext, BackfillPolicy, Config, DailyPartitionsDefinition, asset, define_asset_job

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.git import get_git_commit_short
from posthog.models.raw_sessions.sessions_v3 import (
    GET_NUM_SHARDED_RAW_SESSIONS_ACTIVE_PARTS,
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


class SessionsBackfillConfig(Config):
    """Config for sessions backfill jobs.

    Supports custom clickhouse_settings that will be merged with default settings,
    and team_id chunking to split work into smaller inserts.
    """

    clickhouse_settings: dict[str, Any] | None = None
    team_id_chunks: int | None = 16
    max_unmerged_parts: int = 300
    parts_check_poll_frequency_seconds: int = 30
    parts_check_max_wait_seconds: int = 3600


daily_partitions = DailyPartitionsDefinition(
    start_date="2019-01-01",  # this is a year before posthog was founded, so should be early enough even including data imports
    timezone="UTC",
    end_offset=1,  # include today's partition (note that will create a partition with incomplete data, but all our backfills are idempotent so this is ok providing we re-run later)
)

ONE_HOUR_IN_SECONDS = 60 * 60
ONE_GB_IN_BYTES = 1024 * 1024 * 1024

clickhouse_settings = {
    # see this run which took around 2hrs 10min for 1 day https://posthog.dagster.plus/prod-us/runs/0ba8afaa-f3cc-4845-97c5-96731ec8231d?focusedTime=1762898705269&selection=sessions_v3_backfill&logs=step%3Asessions_v3_backfill
    # so to give some margin, allow 4 hours per partition
    "max_execution_time": MAX_PARTITIONS_PER_RUN * 4 * ONE_HOUR_IN_SECONDS,
    "max_memory_usage": 100 * ONE_GB_IN_BYTES,
    "distributed_aggregation_memory_efficient": "1",
    # use insert_distributed_sync=0 to avoid OOM (even 100GB wasn't enough with sync=1)
    # instead, we use preflight checks on unmerged parts count to prevent TOO_MANY_PARTS errors
    "insert_distributed_sync": "0",
}


def get_partition_where_clause(context: AssetExecutionContext, timestamp_field: str) -> str:
    start_incl = context.partition_time_window.start.strftime("%Y-%m-%d")
    end_excl = context.partition_time_window.end.strftime("%Y-%m-%d")

    # it's ok that we use inclusive equality for both comparisons here, adding events to this table is idempotent
    # so if an event did get added twice on the exact boundary, the data would still be correct
    return f"'{start_incl}' <= {timestamp_field} AND {timestamp_field} <= '{end_excl}'"


def wait_for_parts_to_merge(
    context: AssetExecutionContext,
    config: SessionsBackfillConfig,
    sync_client: Optional[Client] = None,
) -> None:
    """Check for unmerged parts and wait if there are too many.

    Queries system.parts using clusterAllReplicas to count active parts across all nodes,
    and waits until the count drops below the threshold.
    """
    if config.max_unmerged_parts <= 0:
        return

    start_time = time.time()
    first_check = True

    while True:
        # run the query
        result = sync_execute(GET_NUM_SHARDED_RAW_SESSIONS_ACTIVE_PARTS, sync_client=sync_client)
        unmerged_parts_count = result[0][0] if result else 0

        if unmerged_parts_count < config.max_unmerged_parts:
            if not first_check:
                context.log.info(
                    f"Parts merged sufficiently: {unmerged_parts_count} < {config.max_unmerged_parts}. Proceeding."
                )
            return

        elapsed = time.time() - start_time
        if elapsed > config.parts_check_max_wait_seconds:
            raise TimeoutError(
                f"Timed out waiting for parts to merge after {elapsed:.0f}s. "
                f"Current unmerged parts: {unmerged_parts_count}, threshold: {config.max_unmerged_parts}"
            )

        if first_check:
            context.log.info(
                f"Found {unmerged_parts_count} unmerged parts (threshold: {config.max_unmerged_parts}). "
                f"Waiting for parts to merge..."
            )
            first_check = False
        else:
            context.log.info(f"Still waiting... {unmerged_parts_count} unmerged parts after {elapsed:.0f}s")

        time.sleep(config.parts_check_poll_frequency_seconds)


@asset(
    partitions_def=daily_partitions,
    name="sessions_v3_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)
def sessions_v3_backfill(context: AssetExecutionContext, config: SessionsBackfillConfig) -> None:
    _do_backfill(
        timestamp_field="timestamp", sql_template=RAW_SESSION_TABLE_BACKFILL_SQL_V3, config=config, context=context
    )


@asset(
    partitions_def=daily_partitions,
    name="sessions_v3_replay_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)
def sessions_v3_backfill_replay(context: AssetExecutionContext, config: SessionsBackfillConfig) -> None:
    _do_backfill(
        timestamp_field="min_timestamp",
        sql_template=RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3,
        config=config,
        context=context,
    )


sessions_backfill_job = define_asset_job(
    name="sessions_v3_backfill_job",
    selection=["sessions_v3_backfill", "sessions_v3_replay_backfill"],
    partitions_def=daily_partitions,
    tags={"owner": JobOwners.TEAM_ANALYTICS_PLATFORM.value, **CONCURRENCY_TAG},
)


def _do_backfill(
    sql_template: Callable, timestamp_field: str, context: AssetExecutionContext, config: SessionsBackfillConfig
):
    where_clause = get_partition_where_clause(context, timestamp_field=timestamp_field)

    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"

    context.log.info(f"Config: {config}")

    # Merge custom clickhouse settings with defaults
    merged_settings = clickhouse_settings.copy()
    if config.clickhouse_settings:
        merged_settings.update(config.clickhouse_settings)
        context.log.info(f"Using custom ClickHouse settings: {config.clickhouse_settings}")

    team_id_chunks = max(1, config.team_id_chunks or 1)

    context.log.info(
        f"Running backfill for {partition_range_str} (where='{where_clause}') using commit {get_git_commit_short() or 'unknown'} "
    )
    if debug_url := metabase_debug_query_url(context.run_id):
        context.log.info(f"Debug query: {debug_url}")

    cluster = get_cluster()
    tags = dagster_tags(context)

    def backfill_per_shard(client: Client):
        with tags_context(kind="dagster", dagster=tags):
            for chunk_i in range(team_id_chunks):
                # Check for too many unmerged parts before processing each chunk
                wait_for_parts_to_merge(context, config, sync_client=client)

                # Add team_id chunking to the where clause if needed
                if team_id_chunks > 1:
                    chunk_where_clause = f"({where_clause}) AND team_id % {team_id_chunks} = {chunk_i}"
                    context.log.info(
                        f"Processing chunk {chunk_i + 1}/{team_id_chunks} (team_id % {team_id_chunks} = {chunk_i})"
                    )
                else:
                    chunk_where_clause = where_clause

                # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
                # as long as the backfill has run at least once for each partition, the data will be correct
                backfill_sql = sql_template(where=chunk_where_clause, use_sharded_source=True)
                context.log.info(backfill_sql)
                sync_execute(backfill_sql, settings=merged_settings, sync_client=client)

                if team_id_chunks > 1:
                    context.log.info(f"Completed chunk {chunk_i + 1}/{team_id_chunks}")

    cluster.map_one_host_per_shard(backfill_per_shard).result()

    context.log.info(f"Successfully backfilled sessions_v3 for {partition_range_str}")
