import csv
import datetime
import os

from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import ReplacingMergeTree
from posthog.settings import CLICKHOUSE_PASSWORD
from .currencies import SUPPORTED_CURRENCY_CODES


# This loads historical data from `historical.csv`
# and generates a dictionary containing all entries for all dates and all currencies
# from January 1st 2000 to December 31st 2024
#
# All of the rates are in comparison to the USD at that time.
# There's no inflation adjustment, that would be nonsense.
# If you want to convert from currency A to currency B, you need to:
# 1. Convert A to USD
# 2. Convert USD to B
#
# This is easily achieved by: `amount` B = `amount` A * `rate_A` / `rate_B`
#
# This CSV was originally downloaded from https://github.com/xriss/freechange/blob/master/csv/usd_to_xxx_by_day.csv
# and then slightly optimized:
# 1. Remove all dates older than 2000-01-01
# 2. Truncate all rates to 4 decimal places
# 3. Remove USD because it's the base currency, therefore it's always 1:1
# 4. Add some rates for less known currencies from https://fxtop.com/en/historical-currency-converter.php
# 5. Add BTC rates from https://github.com/Habrador/Bitcoin-price-visualization/blob/main/Bitcoin-price-USD.csv, and manual from the cutoff onwards
#
# The resulting CSV is stored in `historical.csv`
#
# This won't return values for dates where we didn't have a value.
# When querying the table/dictionary, you'll need to look for the previous closest date with a value.
def HISTORICAL_EXCHANGE_RATE_DICTIONARY():
    rates_dict = {}
    currencies = []

    # Load the CSV file
    with open(os.path.join(os.path.dirname(__file__), "historical.csv")) as f:
        reader = csv.reader(f)

        # Get header row with currency codes
        currencies = next(reader)
        currencies = [c.strip() for c in currencies]

        # Parse each row
        for row in reader:
            if not row:  # Skip empty rows
                continue

            date_str = row[0].strip()
            try:
                # Parse the date
                date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                date_key = date.strftime("%Y-%m-%d")

                # Create dictionary for this date
                rates = {}
                for i, value in enumerate(row[1:], 1):
                    currency = currencies[i]

                    # The CSV file SHOULD contain only supported currency codes
                    # but let's be sure to not fail for any reason
                    if currency not in SUPPORTED_CURRENCY_CODES:
                        continue

                    # Only add non-empty values
                    value = value.strip()
                    if value:
                        try:
                            rates[currency] = float(value)
                        except ValueError:
                            # Just ignore non-numeric values
                            pass

                rates_dict[date_key] = rates
            except ValueError:
                # Skip rows with invalid dates
                continue

    return rates_dict


# Yield from HISTORICAL_EXCHANGE_RATE_DICTIONARY()
# a tuple in the form of (date, currency, rate)
def HISTORICAL_EXCHANGE_RATE_TUPLES():
    rates_dict = HISTORICAL_EXCHANGE_RATE_DICTIONARY()
    for date, rates in rates_dict.items():
        for currency, rate in rates.items():
            yield (date, currency, rate)


EXCHANGE_RATE_TABLE_NAME = "exchange_rate"
EXCHANGE_RATE_DICTIONARY_NAME = "exchange_rate_dict"


# `version` is used to ensure the latest version is kept, see https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree
def EXCHANGE_RATE_TABLE_SQL(on_cluster=True):
    return """
CREATE TABLE IF NOT EXISTS {table_name} {on_cluster_clause} (
    date Date,
    currency String,
    rate Decimal64(10),
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = {engine}
ORDER BY (date, currency);
""".format(
        table_name=EXCHANGE_RATE_TABLE_NAME,
        engine=ReplacingMergeTree("exchange_rate", ver="version"),
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DROP_EXCHANGE_RATE_TABLE_SQL(on_cluster=True):
    return "DROP TABLE IF EXISTS {table_name} {on_cluster_clause}".format(
        table_name=EXCHANGE_RATE_TABLE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def TRUNCATE_EXCHANGE_RATE_TABLE_SQL(on_cluster=True):
    return "TRUNCATE TABLE IF EXISTS {table_name} {on_cluster_clause}".format(
        table_name=EXCHANGE_RATE_TABLE_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def EXCHANGE_RATE_DATA_BACKFILL_SQL(exchange_rates=None):
    if exchange_rates is None:
        exchange_rates = HISTORICAL_EXCHANGE_RATE_TUPLES()

    values = ",\n".join(f"(toDate('{date}'), '{currency}', {rate})" for date, currency, rate in exchange_rates)

    return f"""
INSERT INTO exchange_rate (date, currency, rate) VALUES
  {values};"""


# Use COMPLEX_KEY_HASHED, as we have a composite key
# Also, note the `anyLast` function, which is used to get the latest rate for a given date and currency
# given that we might have more than one while the merges haven't finished yet
def EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=True):
    return """
CREATE DICTIONARY IF NOT EXISTS {exchange_rate_dictionary_name} {on_cluster_clause} (
    date Date,
    currency String,
    rate Decimal64(10)
)
PRIMARY KEY (date, currency)
SOURCE(CLICKHOUSE(QUERY 'SELECT date, currency, anyLast(rate) AS rate FROM {exchange_rate_table_name} GROUP BY date, currency' PASSWORD '{clickhouse_password}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(COMPLEX_KEY_HASHED())""".format(
        exchange_rate_dictionary_name=EXCHANGE_RATE_DICTIONARY_NAME,
        exchange_rate_table_name=EXCHANGE_RATE_TABLE_NAME,
        clickhouse_password=CLICKHOUSE_PASSWORD,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DROP_EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=True):
    return "DROP DICTIONARY IF EXISTS {dictionary_name} {on_cluster_clause}".format(
        dictionary_name=EXCHANGE_RATE_DICTIONARY_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    ).strip()
