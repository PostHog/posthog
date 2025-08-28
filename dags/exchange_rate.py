import os
import datetime
from typing import Any

import dagster
import requests
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.exchange_rate.currencies import SUPPORTED_CURRENCY_CODES
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DATA_BACKFILL_SQL, EXCHANGE_RATE_DICTIONARY_NAME

from dags.common import JobOwners, settings_with_log_comment

OPEN_EXCHANGE_RATES_API_BASE_URL = "https://openexchangerates.org/api"


class ExchangeRateConfig(dagster.Config):
    """Configuration for the exchange rate API."""

    # NOTE: For local development, you can add this key to a `.env` file in the root of the project
    app_id: str = os.environ.get("OPEN_EXCHANGE_RATES_APP_ID", "")
    api_base_url: str = OPEN_EXCHANGE_RATES_API_BASE_URL


# We'll have one partition for each day, starting from 2025 Jan 1st for the daily job
DAILY_PARTITION_DEFINITION = dagster.DailyPartitionsDefinition(start_date=datetime.datetime(2025, 1, 1))

# And one partition for hourly updates for the hourly job
HOURLY_PARTITION_DEFINITION = dagster.HourlyPartitionsDefinition(
    start_date=datetime.datetime(
        2025, 3, 10
    ),  # Start in March 2025 because that's when we started using hourly updates
    minute_offset=45,  # Run at XX:45 to avoid peak load at the top of the hour
    end_offset=12,  # Generate 12 partitions after the current hour to be safe (1 should be enough, 0 breaks our workflow)
)


def get_date_partition_from_hourly_partition(hourly_partition: str) -> str:
    """
    Convert a hourly partition key to a daily partition key.
    """
    return "-".join(hourly_partition.split("-", 3)[0:3])


@dagster.op(
    retry_policy=dagster.RetryPolicy(
        max_retries=5,
        delay=0.2,  # 200ms
        backoff=dagster.Backoff.EXPONENTIAL,
        jitter=dagster.Jitter.PLUS_MINUS,
    )
)
def fetch_exchange_rates(
    context: dagster.OpExecutionContext, date_str: str, app_id: str, api_base_url: str
) -> dict[str, Any]:
    """
    Fetches exchange rates from the Open Exchange Rates API for a specific date.
    """
    # Construct the API URL
    url = f"{api_base_url}/historical/{date_str}.json"

    # Prepare query parameters
    params = {"app_id": app_id}

    # Make the API request
    context.log.info(f"Fetching exchange rates for {date_str} with params {params}")
    response = requests.get(url, params=params)

    if response.status_code != 200:
        error_msg = f"Failed to fetch exchange rates: {response.status_code} - {response.text}"
        context.log.error(error_msg)
        raise Exception(error_msg)

    # Parse the response
    data = response.json()

    # Log some information about the fetched data
    context.log.info(f"Successfully fetched exchange rates for {date_str}")
    context.log.info(f"Base currency: {data.get('base')}")
    context.log.info(f"Number of rates: {len(data.get('rates', {}))}")

    if not data.get("rates"):
        raise Exception(f"No rates found for {date_str}")

    return data.get("rates")


@dagster.asset(partitions_def=DAILY_PARTITION_DEFINITION)
def daily_exchange_rates(
    context: dagster.AssetExecutionContext, config: ExchangeRateConfig
) -> dagster.Output[dict[str, Any]]:
    """
    Fetches exchange rates from the Open Exchange Rates API for a specific date.
    The date is determined by the partition key, which is in the format %Y-%m-%d.
    """
    date_str = context.partition_key
    app_id = config.app_id
    api_base_url = config.api_base_url

    if not app_id:
        raise ValueError("Open Exchange Rates API key (app_id) is required")

    rates = fetch_exchange_rates(
        context=dagster.build_op_context(), date_str=date_str, app_id=app_id, api_base_url=api_base_url
    )

    return dagster.Output(
        value=rates,
        metadata={
            "date_str": date_str,
            "rates_count": len(rates),
            "rates": rates,
        },
    )


@dagster.asset(partitions_def=HOURLY_PARTITION_DEFINITION)
def hourly_exchange_rates(
    context: dagster.AssetExecutionContext, config: ExchangeRateConfig
) -> dagster.Output[dict[str, Any]]:
    """
    Fetches exchange rates from the Open Exchange Rates API for a specific hour.
    The date is determined by the partition key, which is in the format %Y-%m-%d-%H:%M.
    """
    # Convert hourly partition key to daily format because we always fetch information for the day
    date_str = get_date_partition_from_hourly_partition(context.partition_key)
    app_id = config.app_id
    api_base_url = config.api_base_url

    if not app_id:
        raise ValueError("Open Exchange Rates API key (app_id) is required")

    rates = fetch_exchange_rates(
        context=dagster.build_op_context(), date_str=date_str, app_id=app_id, api_base_url=api_base_url
    )

    return dagster.Output(
        value=rates,
        metadata={
            "date_str": date_str,
            "rates_count": len(rates),
            "rates": rates,
        },
    )


def store_exchange_rates_in_clickhouse(
    context: dagster.OpExecutionContext,
    date_str: str,
    exchange_rates: dict[str, Any],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> tuple[list[dict[str, Any]], list[tuple[str, str, Any]]]:
    """
    Stores exchange rates data in ClickHouse.
    """
    # Transform data into rows for ClickHouse
    rows = [
        {"date": date_str, "currency": currency, "rate": rate}
        for currency, rate in exchange_rates.items()
        if currency in SUPPORTED_CURRENCY_CODES
    ]

    # Log information about the data being stored
    context.log.info(f"Storing {len(rows)} exchange rates for {date_str} in ClickHouse")

    # Prepare values for batch insert
    # Use toDate() to cast the string date to a ClickHouse Date type
    values = [(row["date"], row["currency"], row["rate"]) for row in rows]

    # Execute the insert if there are values to insert
    if values:
        # Batch insert all values
        def insert(client: Client) -> bool:
            try:
                client.execute(
                    EXCHANGE_RATE_DATA_BACKFILL_SQL(exchange_rates=values),
                    settings=settings_with_log_comment(context),
                )
                context.log.info("Successfully inserted exchange rates")
                return True
            except Exception as e:
                context.log.warning(f"Failed to insert exchange rates: {e}")
                return False

        # Simply ask the dictionary to be reloaded with the new data
        def reload_dict(client: Client) -> bool:
            try:
                client.execute(
                    f"SYSTEM RELOAD DICTIONARY {EXCHANGE_RATE_DICTIONARY_NAME}",
                    settings=settings_with_log_comment(context),
                )
                context.log.info("Successfully reloaded exchange_rate_dict dictionary")
                return True
            except Exception as e:
                context.log.warning(f"Failed to reload exchange_rate_dict dictionary: {e}")
                return False

        insert_results = cluster.map_all_hosts(insert).result()
        reload_results = cluster.map_all_hosts(reload_dict).result()

        if not all(insert_results.values()):
            raise Exception(f"Failed to insert some exchange rates, {insert_results}")

        if not all(reload_results.values()):
            raise Exception(f"Failed to reload some exchange_rate_dict dictionaries, {reload_results}")

    else:
        context.log.warning(f"No exchange rates to store for {date_str}")

    return (rows, values)


@dagster.asset(
    partitions_def=DAILY_PARTITION_DEFINITION,
    ins={"exchange_rates": dagster.AssetIn(key=daily_exchange_rates.key)},
)
def daily_exchange_rates_in_clickhouse(
    context: dagster.AssetExecutionContext,
    exchange_rates: dict[str, Any],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Stores exchange rates data in ClickHouse.
    The base currency is always USD as per the table design.
    """
    # Extract data from the input
    date_str = context.partition_key

    # Store the rates in ClickHouse
    rows, values = store_exchange_rates_in_clickhouse(
        context=context, date_str=date_str, exchange_rates=exchange_rates, cluster=cluster
    )

    # Calculate some statistics for metadata
    currencies_count = len(rows)
    min_rate = float(min(row["rate"] for row in rows)) if rows else 0.0
    max_rate = float(max(row["rate"] for row in rows)) if rows else 0.0
    avg_rate = float(sum(row["rate"] for row in rows) / len(rows)) if rows else 0.0

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


@dagster.asset(
    partitions_def=HOURLY_PARTITION_DEFINITION,
    ins={"exchange_rates": dagster.AssetIn(key=hourly_exchange_rates.key)},
)
def hourly_exchange_rates_in_clickhouse(
    context: dagster.AssetExecutionContext,
    exchange_rates: dict[str, Any],
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.MaterializeResult:
    """
    Stores exchange rates data in ClickHouse.
    The base currency is always USD as per the table design.
    """
    # Extract data from the input
    date_str = get_date_partition_from_hourly_partition(context.partition_key)

    # Store the rates in ClickHouse
    rows, values = store_exchange_rates_in_clickhouse(
        context=context, date_str=date_str, exchange_rates=exchange_rates, cluster=cluster
    )

    # Calculate some statistics for metadata
    currencies_count = len(rows)
    min_rate = float(min(row["rate"] for row in rows)) if rows else 0.0
    max_rate = float(max(row["rate"] for row in rows)) if rows else 0.0
    avg_rate = float(sum(row["rate"] for row in rows) / len(rows)) if rows else 0.0

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


# Create jobs from the assets
daily_exchange_rates_job = dagster.define_asset_job(
    name="daily_exchange_rates_job",
    selection=[daily_exchange_rates.key, daily_exchange_rates_in_clickhouse.key],
    tags={"owner": JobOwners.TEAM_REVENUE_ANALYTICS.value},
)

hourly_exchange_rates_job = dagster.define_asset_job(
    name="hourly_exchange_rates_job",
    selection=[hourly_exchange_rates.key, hourly_exchange_rates_in_clickhouse.key],
    tags={"owner": JobOwners.TEAM_REVENUE_ANALYTICS.value},
)


# Create daily/hourly schedules with different cron schedules
@dagster.schedule(
    job=daily_exchange_rates_job,
    cron_schedule="28 0 * * *",  # Run at 00:28 AM every day, random minute to avoid peak load
)
def daily_exchange_rates_schedule(context):
    """Process previous day's exchange rates data."""
    # Calculate the previous day's date
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    timestamp = previous_day.strftime("%Y-%m-%d")
    return dagster.RunRequest(run_key=timestamp, partition_key=timestamp)


@dagster.schedule(
    job=hourly_exchange_rates_job,
    cron_schedule=HOURLY_PARTITION_DEFINITION.get_cron_schedule(),
)
def hourly_exchange_rates_schedule(context):
    """Process current day's exchange rates data for this hour."""
    current_hour = context.scheduled_execution_time
    timestamp = current_hour.strftime("%Y-%m-%d-%H:%M")
    return dagster.RunRequest(run_key=timestamp, partition_key=timestamp)
