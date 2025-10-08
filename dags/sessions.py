from dagster import AssetExecutionContext, BackfillPolicy, MonthlyPartitionsDefinition, asset

from posthog.clickhouse.client import sync_execute
from posthog.models.raw_sessions.sql_v3 import RAW_SESSION_TABLE_BACKFILL_SQL_V3

# Each partition is pretty heavy, as it's an entire month of events, so this number doesn't need to be high
MAX_PARTITIONS_PER_RUN = 3

RESTRICTED_TEAM_IDS = [1, 2]  # only run the backfill on posthog teams for now

monthly_partitions = MonthlyPartitionsDefinition(
    start_date="2019-01-01",  # this is a year before posthog was founded, so should be early enough even including data imports
)


def get_partion_where_clause(context: AssetExecutionContext) -> str:
    start_incl = context.partition_time_window.start.strftime("%Y-%m-%d")
    end_excl = context.partition_time_window.end.strftime("%Y-%m-%d")

    # it's ok that we use inclusive equality for both comparisons here, adding events to this table is idempotent
    # so if an event did get added twice on the exact boundary, the data would still be correct
    return f"'{start_incl}' <= timestamp AND timestamp <= '{end_excl}'"


@asset(
    partitions_def=monthly_partitions,
    name="sessions_v3_backfill",
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=MAX_PARTITIONS_PER_RUN),
)
def sessions_v3_backfill(context: AssetExecutionContext):
    where_clause = get_partion_where_clause(context)
    if RESTRICTED_TEAM_IDS:
        where_clause += f" AND team_id IN ({', '.join(str(t) for t in RESTRICTED_TEAM_IDS)})"

    # note that this is idempotent, so we don't need to worry about running it multiple times for the same partition
    # as long as the backfill has run at least once for each partition, the data will be correct
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL_V3(where=where_clause)

    context.log.info(f"Running backfill for {context.partition_key} (where='{where_clause}')")

    sync_execute(backfill_sql)

    context.log.info(f"Successfully backfilled sessions_v3 for {context.partition_key}")

    return f"Backfilled {context.partition_key}"
