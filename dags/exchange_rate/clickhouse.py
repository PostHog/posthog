from typing import Any

import dagster

from .exchange_rate import exchange_rates
from clickhouse_driver import Client
from posthog.clickhouse.cluster import ClickhouseCluster, NodeRole


# TODO: Use the constants from `posthog/models/exchange_rate/sql.py` once that's merged
# rather than hardcoding the table/dict name here
@dagster.asset(
    partitions_def=dagster.DailyPartitionsDefinition(start_date="2025-01-01"),
    group_name="exchange_rates",
    ins={"exchange_rates": dagster.AssetIn(key=exchange_rates.key)},
)
def store_exchange_rates_in_clickhouse(
    context: dagster.AssetExecutionContext,
    exchange_rates: dict[str, Any],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Stores exchange rates data in ClickHouse.

    This asset depends on the exchange_rates asset and will be executed
    after it completes successfully.

    The base currency is always USD as per the table design.
    """
    # Extract data from the input
    date_str = context.partition_key

    # Transform data into rows for ClickHouse
    rows = [{"date": date_str, "currency": currency, "rate": rate} for currency, rate in exchange_rates.items()]

    # Log information about the data being stored
    context.log.info(f"Storing {len(rows)} exchange rates for {date_str} in ClickHouse")

    # Prepare values for batch insert
    # Use toDate() to cast the string date to a ClickHouse Date type
    values = [f"(toDate('{row['date']}'), '{row['currency']}', {row['rate']})" for row in rows]

    # Execute the insert if there are values to insert
    insert_sql = ""
    if values:
        insert_sql = f"""
        INSERT INTO exchange_rate (date, currency, rate)
        VALUES {', '.join(values)}
        """

        def insert(client: Client):
            try:
                # Batch insert all values
                client.sync_execute(insert_sql)
                context.log.info("Successfully inserted exchange rates")
            except Exception as e:
                context.log.warning(f"Failed to insert exchange rates: {e}")

        def reload_dict(client: Client):
            try:
                client.sync_execute("SYSTEM RELOAD DICTIONARY exchange_rate_dict")
                context.log.info("Successfully reloaded exchange_rate_dict dictionary")
            except Exception as e:
                context.log.warning(f"Failed to reload exchange_rate_dict dictionary: {e}")

        cluster.map_hosts_by_role(insert, NodeRole.DATA).result()
        cluster.map_hosts_by_role(reload_dict, NodeRole.DATA).result()
    else:
        context.log.warning(f"No exchange rates to store for {date_str}")

    # Calculate some statistics for metadata
    currencies_count = len(rows)
    min_rate = min(row["rate"] for row in rows) if rows else 0.0
    max_rate = max(row["rate"] for row in rows) if rows else 0.0
    avg_rate = sum(row["rate"] for row in rows) / len(rows) if rows else 0.0

    # Return the rows with metadata
    return dagster.MaterializeResult(
        metadata={
            "date": dagster.MetadataValue.text(date_str),
            "base_currency": dagster.MetadataValue.text("USD"),  # Always USD as per table design
            "currencies_count": dagster.MetadataValue.int(currencies_count),
            "min_rate": dagster.MetadataValue.float(min_rate),
            "max_rate": dagster.MetadataValue.float(max_rate),
            "avg_rate": dagster.MetadataValue.float(avg_rate),
            "values": dagster.MetadataValue.json(values),
        }
    )
