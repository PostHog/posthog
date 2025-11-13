from clickhouse_driver import Client
from dagster import AssetExecutionContext, BackfillPolicy, DailyPartitionsDefinition, asset

from posthog.clickhouse.cluster import get_cluster
from posthog.git import get_git_commit_short
from posthog.models.raw_sessions.sessions_v3 import (
    RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3,
    RAW_SESSION_TABLE_BACKFILL_SQL_V3,
)

# This is the number of days to backfill in one SQL operation
MAX_PARTITIONS_PER_RUN = 30

daily_partitions = DailyPartitionsDefinition(
    start_date="2019-01-01",  # this is a year before posthog was founded, so should be early enough even including data imports
    timezone="UTC",
)


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
)
def sessions_v3_backfill(context: AssetExecutionContext) -> None:
    where_clause = get_partition_where_clause(context, timestamp_field="timestamp")

    # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
    # as long as the backfill has run at least once for each partition, the data will be correct
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL_V3(where=where_clause)

    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"
    context.log.info(
        f"Running backfill for {partition_range_str} (where='{where_clause}') using commit {get_git_commit_short() or 'unknown'} "
    )
    context.log.info(backfill_sql)

    cluster = get_cluster()

    def backfill_per_shard(client: Client):
        client.execute(backfill_sql)

    cluster.map_one_host_per_shard(backfill_per_shard)

    context.log.info(f"Successfully backfilled sessions_v3 for {partition_range_str}")


@asset(
    partitions_def=daily_partitions,
    name="sessions_v3_replay_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
)
def sessions_v3_backfill_replay(context: AssetExecutionContext) -> None:
    where_clause = get_partition_where_clause(context, timestamp_field="min_first_timestamp")

    # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
    # as long as the backfill has run at least once for each partition, the data will be correct
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_RECORDINGS_SQL_V3(where=where_clause)

    partition_range = context.partition_key_range
    partition_range_str = f"{partition_range.start} to {partition_range.end}"
    context.log.info(
        f"Running backfill for {partition_range_str} (where='{where_clause}') using commit {get_git_commit_short() or 'unknown'} "
    )
    context.log.info(backfill_sql)

    cluster = get_cluster()

    def backfill_per_shard(client: Client):
        client.execute(backfill_sql)

    cluster.map_one_host_per_shard(backfill_per_shard)

    context.log.info(f"Successfully backfilled sessions_v3 for {partition_range_str}")
