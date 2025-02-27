import os
import requests
from datetime import datetime
from typing import Any

import dagster

API_BASE_URL = "https://openexchangerates.org/api"


class ExchangeRateConfig(dagster.Config):
    """Configuration for the exchange rate API."""

    app_id: str = os.environ.get("OPEN_EXCHANGE_RATES_APP_ID", "")
    api_base_url: str = API_BASE_URL


# We'll have one partition for each day, starting from 2025-01-01
PARTITION_DEFINITION = dagster.DailyPartitionsDefinition(start_date="2025-01-01")


@dagster.asset(partitions_def=PARTITION_DEFINITION)
def exchange_rates(context: dagster.AssetExecutionContext, config: ExchangeRateConfig) -> dict[str, Any]:
    """
    Fetches exchange rates from the Open Exchange Rates API for a specific date.

    The date is determined by the partition key, which is in the format YYYY-MM-DD.
    """
    date_str = context.partition_key
    app_id = config.app_id
    api_base_url = config.api_base_url

    if not app_id:
        raise ValueError("Open Exchange Rates API key (app_id) is required")

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

    # Return only the rates hash
    return data.get("rates")


# Create partitioned asset jobs, daily and hourly
daily_exchange_rates_job = dagster.define_asset_job(
    name="daily_exchange_rates_job",
    selection=[exchange_rates],
)

hourly_exchange_rates_job = dagster.define_asset_job(
    name="hourly_exchange_rates_job",
    selection=[exchange_rates],
)


# Create daily/hourly schedules with different cron schedules
@dagster.schedule(
    job=daily_exchange_rates_job,
    cron_schedule="0 1 * * *",  # Run at 1:00 AM every day
)
def daily_exchange_rates_schedule(context):
    """Process previous day's exchange rates data."""
    # Calculate the previous day's date
    previous_day = context.scheduled_execution_time.date() - datetime.timedelta(days=1)
    date = previous_day.strftime("%Y-%m-%d")
    return dagster.RunRequest(run_key=date, partition_key=date)


@dagster.schedule(
    job=hourly_exchange_rates_job,
    cron_schedule="0 * * * *",  # Run every hour
)
def hourly_exchange_rates_schedule(context):
    """Process current day's exchange rates data."""
    current_day = context.scheduled_execution_time.date()
    date = current_day.strftime("%Y-%m-%d")
    return dagster.RunRequest(run_key=date, partition_key=date)
