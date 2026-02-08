import time
import base64
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings

from clickhouse_driver import Client
from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    Config,
    DailyPartitionsDefinition,
    PartitionedConfig,
    asset,
    define_asset_job,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import NodeRole, Workload
from posthog.clickhouse.cluster import get_cluster
from posthog.clickhouse.query_tagging import tags_context
from posthog.cloud_utils import is_cloud
from posthog.dags.common.common import JobOwners, dagster_tags
from posthog.git import get_git_commit_short
from posthog.models.raw_sessions.sessions_v3 import (
    GET_NUM_SHARDED_RAW_SESSIONS_ACTIVE_PARTS,
    RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3,
    RAW_SESSION_TABLE_BACKFILL_SQL_V3,
)

# This is the number of days to backfill in one SQL operation
MAX_PARTITIONS_PER_RUN = 1

# Keep the number of concurrent runs low to avoid overloading ClickHouse and running into the dread "Too many parts".
# This tag needs to also exist in Dagster Cloud (and the local dev dagster.yaml) for the concurrency limit to take effect.
#
# We use two levels of concurrency control:
# 1. Global limit on total concurrent sessions backfill runs
# 2. Per-DB-partition limit to ensure only one insert per shard per ClickHouse partition (YYYYMM)
#
# We use two tag keys (_0 and _1) because events from the 1st of a month can write to both
# the previous and current month's DB partitions (sessions can span midnight).
# See tags_for_sessions_partition() for details.
#
# dagster.yaml configuration:
#   concurrency:
#     runs:
#       tag_concurrency_limits:
#         - key: 'sessions_backfill_concurrency'
#           limit: 3
#         - key: 'sessions_db_partition_0'
#           limit: 1
#           value:
#             applyLimitPerUniqueValue: true
#         - key: 'sessions_db_partition_1'
#           limit: 1
#           value:
#             applyLimitPerUniqueValue: true
CONCURRENCY_TAG = {
    "sessions_backfill_concurrency": "sessions_v3",
}


def tags_for_sessions_partition(partition_key: str) -> dict[str, str]:
    """Generate tags for a sessions backfill partition.

    Uses two tag keys (sessions_db_partition_0 and sessions_db_partition_1) to ensure
    only one concurrent insert per DB partition.

    _0 is the current day's month, _1 is the previous day's month. These are usually
    the same, but differ on the 1st of each month. This handles sessions spanning
    midnight at month boundaries.

    Example tags:
    - 2025-10-31: {_0: "202510", _1: "202510"}
    - 2025-11-01: {_0: "202511", _1: "202510"}
    - 2025-11-02: {_0: "202511", _1: "202511"}

    With applyLimitPerUniqueValue on both keys:
    - 2025-10-31 vs 2025-11-01: Both have 202510 in _1 → blocked
    - 2025-11-01 vs 2025-11-02: Both have 202511 in _0 → blocked
    - 2025-10-01 vs 2025-11-01 vs 2025-12-01: Different values in both → allowed
    """

    date = datetime.strptime(partition_key, "%Y-%m-%d")
    prev_date = date - timedelta(days=1)

    return {
        "sessions_db_partition_0": "s0_" + date.strftime("%Y%m"),
        "sessions_db_partition_1": "s1_" + prev_date.strftime("%Y%m"),
    }


class SessionsBackfillConfig(Config):
    """Config for sessions backfill jobs.

    Supports custom clickhouse_settings that will be merged with default settings,
    and team_id chunking to split work into smaller inserts.
    """

    clickhouse_settings: dict[str, Any] | None = None
    team_id_chunks: int | None = 16
    max_unmerged_parts: int = 100
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


def get_db_partitions_to_check(context: AssetExecutionContext) -> list[str]:
    """Calculate all ClickHouse DB partitions (YYYYMM) that might be affected by this backfill.

    Since sessions can last 24 hours, we need to check partitions starting from 1 day before
    the Dagster partition range through the end of the range.

    Args:
        context: The Dagster execution context with partition_time_window

    Returns:
        Sorted list of DB partition names in YYYYMM format (e.g., ['202412', '202501'])
    """
    # Start 24 hours before the range to account for sessions that started the previous day
    start_date = context.partition_time_window.start - timedelta(days=1)
    end_date = context.partition_time_window.end

    # Collect all unique YYYYMM partitions in the date range
    db_partitions = set()
    current_date = start_date
    while current_date <= end_date:
        db_partitions.add(current_date.strftime("%Y%m"))
        current_date += timedelta(days=1)

    return sorted(db_partitions)


def wait_for_parts_to_merge(
    context: AssetExecutionContext,
    config: SessionsBackfillConfig,
    sync_client: Optional[Client] = None,
) -> None:
    """Check for unmerged parts and wait if there are too many.

    Queries system.parts using clusterAllReplicas to count active parts in the target partitions,
    and waits until the count drops below the threshold.
    """
    if config.max_unmerged_parts <= 0:
        return

    # Calculate all DB partitions (YYYYMM) that might be affected
    partitions = get_db_partitions_to_check(context)

    start_time = time.time()
    first_check = True

    while True:
        # Check parts across all relevant partitions
        query = GET_NUM_SHARDED_RAW_SESSIONS_ACTIVE_PARTS(partitions)
        result = sync_execute(query, sync_client=sync_client)
        (unmerged_parts_count, max_partition, max_host) = result[0]

        if unmerged_parts_count < config.max_unmerged_parts:
            context.log.info(
                f"Acceptable number of active parts in partitions {partitions}: {unmerged_parts_count} < {config.max_unmerged_parts}, proceeding..."
            )
            return

        elapsed = time.time() - start_time
        if elapsed > config.parts_check_max_wait_seconds:
            raise TimeoutError(
                f"Timed out waiting for parts to merge in partitions {partitions} after {elapsed:.0f}s. "
                f"Current unmerged parts: {unmerged_parts_count}, threshold: {config.max_unmerged_parts} "
                f"Max was on partition {max_partition} on host {max_host}. "
            )

        if first_check:
            context.log.info(
                f"Found {unmerged_parts_count} unmerged parts in partitions {partitions} (threshold: {config.max_unmerged_parts}). "
                f"Max was on partition {max_partition} on host {max_host}. "
                f"Waiting for parts to merge..."
            )
            first_check = False
        else:
            context.log.info(
                f"Still waiting... {unmerged_parts_count} unmerged parts in partitions {partitions} after {elapsed:.0f}s. "
                f"Max was on partition {max_partition} on host {max_host}. "
            )

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


sessions_backfill_partitioned_config = PartitionedConfig(
    partitions_def=daily_partitions,
    run_config_for_partition_key_fn=lambda partition_key: {},
    tags_for_partition_key_fn=tags_for_sessions_partition,
)

sessions_backfill_job = define_asset_job(
    name="sessions_v3_backfill_job",
    selection=["sessions_v3_backfill", "sessions_v3_replay_backfill"],
    config=sessions_backfill_partitioned_config,
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
        f"Running backfill for Dagster partitions {partition_range_str} "
        f"(where='{where_clause}') "
        f"using commit {get_git_commit_short() or 'unknown'}"
    )
    if debug_url := metabase_debug_query_url(context.run_id):
        context.log.info(f"Debug query: {debug_url}")

    cluster = get_cluster()
    tags = dagster_tags(context)

    num_shards = cluster.num_shards
    context.log.info(f"Cluster has shards {cluster.shards}, using num_shards={num_shards} for shard filtering")

    def make_backfill_fn(shard_num: int) -> Callable[[Client], None]:
        def backfill_for_shard(client: Client):
            shard_index = shard_num - 1  # Convert 1-indexed to 0-indexed
            context.log.info(f"Starting backfill on shard {shard_num} (shard_index={shard_index})")

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
                    backfill_sql = sql_template(
                        where=chunk_where_clause,
                        shard_index=shard_index,
                        num_shards=num_shards,
                    )
                    context.log.info(backfill_sql)
                    sync_execute(backfill_sql, settings=merged_settings, sync_client=client)

                    if team_id_chunks > 1:
                        context.log.info(f"Completed chunk {chunk_i + 1}/{team_id_chunks}")

            context.log.info(f"Completed backfill on shard {shard_num}")

        return backfill_for_shard

    workload, node_role = (Workload.OFFLINE, NodeRole.DATA) if is_cloud() else (Workload.DEFAULT, NodeRole.ALL)

    cluster.map_any_host_in_shards_by_role(
        shard_fns={shard: make_backfill_fn(shard) for shard in cluster.shards},
        workload=workload,
        node_role=node_role,
    ).result()

    context.log.info(f"Successfully backfilled sessions_v3 for Dagster partitions {partition_range_str}")


def metabase_debug_query_url(run_id: str) -> Optional[str]:
    cloud_deployment = getattr(settings, "CLOUD_DEPLOYMENT", None)
    if cloud_deployment == "US":
        return f"https://metabase.prod-us.posthog.dev/question/1671-get-clickhouse-query-log-for-given-dagster-run-id?dagster_run_id={run_id}"
    if cloud_deployment == "EU":
        return f"https://metabase.prod-eu.posthog.dev/question/544-get-clickhouse-query-log-for-given-dagster-run-id?dagster_run_id={run_id}"
    sql = f"""
SELECT
    hostName() as host,
    event_time,
    type,
    exception IS NOT NULL and exception != '' as has_exception,
    query_duration_ms,
    formatReadableSize(memory_usage) as memory_used,
    formatReadableSize(read_bytes) as data_read,
    JSONExtractString(log_comment, 'dagster', 'run_id') AS dagster_run_id,
    JSONExtractString(log_comment, 'dagster', 'job_name') AS dagster_job_name,
    JSONExtractString(log_comment, 'dagster', 'asset_key') AS dagster_asset_key,
    JSONExtractString(log_comment, 'dagster', 'op_name') AS dagster_op_name,
    exception,
    query
FROM clusterAllReplicas('posthog', system.query_log)
WHERE
    dagster_run_id = '{run_id}'
    AND event_date >= today() - 1
ORDER BY event_time DESC;
"""
    return f"http://localhost:8123/play?user=default#{base64.b64encode(sql.encode('utf-8')).decode('utf-8')}"
