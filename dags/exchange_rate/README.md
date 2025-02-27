# Exchange Rate Workflow

This workflow fetches exchange rates from the Open Exchange Rates API and stores them in ClickHouse.

## Components

1. **Exchange Rate Fetcher (`exchange_rate.py`)**

    - Fetches exchange rates from the Open Exchange Rates API
    - Implements a proper asset-based approach where jobs materialize assets
    - Uses a reusable `fetch_exchange_rates_core` op for the core API interaction logic
    - Provides rich metadata about the fetched exchange rates
    - Uses scheduler context to determine dates, ensuring accuracy around midnight
    - Includes a daily scheduled job to materialize the asset for yesterday's exchange rates
    - Includes an hourly scheduled job to materialize the asset for the latest rates for the current day
    - Jobs automatically trigger downstream assets through the dependency chain

2. **ClickHouse Storage (`clickhouse.py`)**
    - Stores exchange rates in ClickHouse with USD as the base currency
    - Uses a simple table structure with date, currency, and rate columns
    - Assumes USD as the base currency (as per table design)
    - Automatically reloads the `exchange_rate_dict` dictionary after inserting new data
    - Provides utility functions for querying exchange rate data
    - Returns metadata with statistics about the stored data

## ClickHouse Table Structure

The exchange rates are stored in a ClickHouse table with the following structure:

```sql
CREATE TABLE IF NOT EXISTS exchange_rate ON CLUSTER '{cluster}' (
    date Date,
    currency String,
    rate Decimal64(4),
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = ReplacingMergeTree(version)
ORDER BY (date, currency);
```

Note that the base currency is always USD, so it's not stored in the table.

A ClickHouse dictionary named `exchange_rate_dict` is also created to provide fast lookups of exchange rates. This dictionary is automatically reloaded after new data is inserted.

You can refer to the most up-to-date structure in [here](../../posthog/models/exchange_rate/sql.py)

## Data Flow

1. The exchange rate data is fetched from the Open Exchange Rates API using the `fetch_exchange_rates_core` op
2. The data is transformed into rows with date, currency, and rate
3. The rows are inserted into the ClickHouse table using proper date casting with `toDate()`
4. The `exchange_rate_dict` dictionary is reloaded to make the new rates immediately available
5. Metadata about the operation is returned for monitoring

## Scheduler Context

The workflow uses the scheduler context to determine dates:

1. For the daily job, it uses the scheduled execution time minus one day
2. For the hourly job, it uses the scheduled execution time directly
3. If no scheduled execution time is available, it falls back to the current time

This ensures that jobs running around midnight use the correct date, even if there's a delay in execution.

## Configuration

The workflow requires an API key from Open Exchange Rates. Set the following environment variable:

```
OPEN_EXCHANGE_RATES_APP_ID=your_api_key_here
```

The `store_exchange_rates_in_clickhouse` asset requires a `ClickhouseCluster` resource, which should be provided by the Dagster environment.

## Partitioning

Both assets use daily partitions starting from January 1, 2025 (`DailyPartitionsDefinition(start_date="2025-01-01")`).

## Usage

### Running the Daily Job Manually

```bash
dagster job execute -m posthog.dags.exchange_rate -j daily_exchange_rates_job
```

### Running the Hourly Job Manually

```bash
dagster job execute -m posthog.dags.exchange_rate -j hourly_current_day_exchange_rates_job
```

### Materializing the Exchange Rate Asset for a Specific Date

```bash
dagster asset materialize -m posthog.dags.exchange_rate -a fetch_exchange_rates --partition 2023-01-01
```

### Materializing the ClickHouse Storage Asset for a Specific Date

```bash
dagster asset materialize -m posthog.dags.exchange_rate -a store_exchange_rates_in_clickhouse --partition 2023-01-01
```

## Schedules

The workflow includes two schedules:

1. **Daily Schedule**: Runs at 1 AM UTC every day to fetch the previous day's exchange rates.
2. **Hourly Schedule**: Runs at the top of every hour to fetch the latest exchange rates for the current day.

## Metadata

Both assets in this workflow return rich metadata:

1. **Exchange Rate Asset Metadata**:

    - Date of the exchange rates
    - Base currency
    - Number of currencies
    - Timestamp from the API
    - Sample of the rates

2. **ClickHouse Storage Asset Metadata**:
    - Date of the exchange rates
    - Base currency (always USD)
    - Number of currencies stored
    - Minimum, maximum, and average rates
    - Sample of the values to be stored

This metadata is visible in the Dagster UI and helps with monitoring and debugging.

## Error Handling

The asset includes the following error handling:

1. Handles empty rate data gracefully (logs a warning but doesn't fail)
2. Catches and logs exceptions during ClickHouse operations (insert and dictionary reload)
3. Continues execution even if the dictionary reload fails (logs a warning)

## Testing

The code includes unit tests that use mocks to test the functionality without requiring a real ClickHouse connection. This makes the tests faster and more reliable.

Run the tests with:

```bash
pytest dags/exchange_rate/tests/test_exchange_rate.py
pytest dags/exchange_rate/tests/test_clickhouse.py
```

The tests verify:

-   Correct SQL generation
-   Proper handling of empty data
-   Error handling during ClickHouse operations
-   Correct metadata generation
-   Dictionary reload functionality
