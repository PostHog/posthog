import csv
import datetime
import os
import re

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
    currency String,
    date Date,
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

    values = ",\n".join(f"('{currency}', {rate}, toDate('{date}'))" for date, currency, rate in exchange_rates)

    return f"""
INSERT INTO exchange_rate (currency, rate, date) VALUES
  {values};"""


# Query used by the dictionary to get the latest rate for a given date and currency
# There's some magic here to get the end date for each rate
#
# The `leadInFrame` function is used to get the next date for each currency
# The `PARTITION BY currency ORDER BY date ASC` is used to ensure the dates are sorted
# The `ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING` is used to get the next date for each currency
#
# The `argMax` function is used to get the latest rate for a given date and currency
# which is necessary because we're using the `ReplacingMergeTree` engine which will keep
# multiple versions of the same rate for the same date and currency until we eventually merge all rows.
#
# We use `0::Date` to represent the date `1970-01-01` because that's the first date in the CSV file.
# If we don't do that the last returned end_date will be `1970-01-01` and that's not what we want.
# If we keep that, then we'll never match it because `end_date` < `start_date`, so we edge-case it
# to return NULL which implies it's an open-ended range - because it is.
#
# All the extra `strip` and `replace`, and `re.sub` are used to make the query
# more readable when running/debugging it.
#
# NOTE: You need to use currency, start_date and end_date in this specific order
# in the outer query or else the dictionary will not work.
# This is for legacy reasons - from the time when Clickhouse
# config was based on an XML file.
EXCHANGE_RATE_DICTIONARY_QUERY = f"""
    SELECT
        currency,
        date AS start_date,
        IF(next_date = 0::Date, NULL, next_date) AS end_date,
        rate
    FROM (
        SELECT
            currency,
            date,
            leadInFrame(date) OVER w AS next_date,
            argMax(rate, version) AS rate
        FROM exchange_rate
        GROUP BY date, currency
        WINDOW w AS (PARTITION BY currency ORDER BY date ASC ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING)
    )
""".replace("\n", " ").strip()
EXCHANGE_RATE_DICTIONARY_QUERY = re.sub(r"\s\s+", " ", EXCHANGE_RATE_DICTIONARY_QUERY)


# Use RANGE_HASHED to simplify queries by date
#
# Because our underlying table is sparse (i.e. we don't have currencies for every date),
# we'll create the concept of a "range" for each currency, which will be the date range
# that a specific rate is valid for.
#
# Ideally, we'd set the `end_date` but we don't need that because Clickhouse has good
# support for open-ended ranges, and therefore we always set it to NULL.
# The `range_lookup_strategy 'max'` declaration will ensure that
# we always get the latest rate for a given date and currency.
#
# Also, note the `anyLast` function on the query construction
# It is used to get the latest rate for a given date and currency from the underlying table
# given that we might have more than one while the merges haven't finished yet
def EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=True):
    return """
CREATE DICTIONARY IF NOT EXISTS {exchange_rate_dictionary_name} {on_cluster_clause} (
    currency String,
    start_date Date,
    end_date Nullable(Date),
    rate Decimal64(10)
)
PRIMARY KEY currency
SOURCE(CLICKHOUSE(QUERY '{query}' PASSWORD '{clickhouse_password}'))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(RANGE_HASHED(range_lookup_strategy 'max'))
RANGE(MIN start_date MAX end_date)""".format(
        exchange_rate_dictionary_name=EXCHANGE_RATE_DICTIONARY_NAME,
        query=EXCHANGE_RATE_DICTIONARY_QUERY,
        clickhouse_password=CLICKHOUSE_PASSWORD,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    )


def DROP_EXCHANGE_RATE_DICTIONARY_SQL(on_cluster=True):
    return "DROP DICTIONARY IF EXISTS {dictionary_name} {on_cluster_clause}".format(
        dictionary_name=EXCHANGE_RATE_DICTIONARY_NAME,
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
    ).strip()
