from datetime import datetime

from dagster import AssetExecutionContext, MonthlyPartitionsDefinition, asset
from dateutil.relativedelta import relativedelta

from posthog.clickhouse.client import sync_execute
from posthog.models.raw_sessions.sql_v3 import RAW_SESSION_TABLE_BACKFILL_SQL_V3

monthly_partitions = MonthlyPartitionsDefinition(
    start_date="2019-01-01"
)  # this is a year before posthog was founded, so should be early enough even including data imports


def partion_key_to_where_clause(partition_key: str) -> str:
    partition_start_date_incl = datetime.strptime(partition_key, "%Y-%m-%d")
    partition_end_date_excl = partition_start_date_incl + relativedelta(months=1)

    start_incl = partition_start_date_incl.strftime("%Y-%m-%d")
    end_excl = partition_end_date_excl.strftime("%Y-%m-%d")

    return f"'{start_incl}' <= timestamp AND timestamp < '{end_excl}'"


@asset(partitions_def=monthly_partitions, name="sessions_v3_backfill")
def sessions_v3_backfill(context: AssetExecutionContext):
    where_clause = partion_key_to_where_clause(context.partition_key)

    # Generate the SQL using your existing function
    backfill_sql = RAW_SESSION_TABLE_BACKFILL_SQL_V3(where=where_clause)

    context.log.info(f"Running backfill for {context.partition_key} (where='{where_clause}')")

    sync_execute(backfill_sql)

    context.log.info(f"Successfully backfilled sessions_v3 for {context.partition_key}")

    return f"Backfilled {context.partition_key}"
