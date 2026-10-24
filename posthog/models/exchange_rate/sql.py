import os
import re
import csv
import datetime

from posthog.exchange_rate_constants import EXCHANGE_RATE_DICTIONARY_NAME as EXCHANGE_RATE_DICTIONARY_NAME
from posthog.settings.data_stores import CLICKHOUSE_DATABASE

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
    csv_path = os.path.join(os.path.dirname(__file__), "historical.csv")
    if not os.path.exists(csv_path):
        # `historical.csv` is a large (~9MB) git-tracked asset that ships with the repo.
        # When it's missing the checkout is incomplete (e.g. a partial/sparse clone or a
        # sandboxed environment that skipped large files), not a logic bug — so surface an
        # actionable message instead of a bare FileNotFoundError from `open` below.
        raise FileNotFoundError(
            f"Exchange rate data file not found at {csv_path}. "
            "This file is tracked in git and required to backfill ClickHouse exchange rates; "
            "ensure your checkout includes it (a partial or sparse clone may have skipped it)."
        )

    with open(csv_path) as f:
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


# Re-exported from the Django-free posthog.exchange_rate_constants module so the HogQL engine can
# use them without booting Django; kept importable here for existing callers.
from posthog.exchange_rate_constants import EXCHANGE_RATE_TABLE_NAME  # noqa: E402


def EXCHANGE_RATE_DATA_BACKFILL_SQL(exchange_rates=None):
    if exchange_rates is None:
        exchange_rates = HISTORICAL_EXCHANGE_RATE_TUPLES()

    values = ",\n".join(f"(toDate('{date}'), '{currency}', {rate})" for date, currency, rate in exchange_rates)

    return f"""
INSERT INTO `{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_TABLE_NAME}` (date, currency, rate) VALUES
  {values};"""


# Query used by the dictionary to get the latest rate for a given date and currency
# There's some magic here to get the end date for each rate
#
# The `leadInFrame` function is used to get the next date for each currency
# defaulting to NULL if there's no next date - if not added, will default to 1970-01-01 which is wrong
# The `PARTITION BY currency ORDER BY date ASC` is used to ensure the dates are sorted
# The `ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING` is used to get the next date for each currency
#
# The `argMax` function is used to get the latest rate for a given date and currency
# which is necessary because we're using the `ReplacingMergeTree` engine which will keep
# multiple versions of the same rate for the same date and currency until we eventually merge all rows.
#
# All the extra `strip` and `replace`, and `re.sub` are used to make the query
# more readable when running/debugging it.
#
# NOTE: You need to use currency, start_date and end_date in this specific order
# in the outer query or else the dictionary will not work.
# This is for legacy reasons - from the time when Clickhouse
# config was based on an XML file.
EXCHANGE_RATE_DICTIONARY_QUERY = (
    """
SELECT
    currency,
    date AS start_date,
    leadInFrame(date::Nullable(Date), 1, NULL::Nullable(Date)) OVER w AS end_date,
    argMax(rate, version) AS rate
FROM
    {table_name}
GROUP BY
    date,
    currency
WINDOW w AS (
    PARTITION
        BY currency
        ORDER BY date ASC
        ROWS BETWEEN 1 FOLLOWING AND 1 FOLLOWING
)
""".format(table_name=f"`{CLICKHOUSE_DATABASE}`.`{EXCHANGE_RATE_TABLE_NAME}`")
    .replace("\n", " ")
    .strip()
)
EXCHANGE_RATE_DICTIONARY_QUERY = re.sub(r"\s\s+", " ", EXCHANGE_RATE_DICTIONARY_QUERY)
