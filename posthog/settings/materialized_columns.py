import os

from posthog.settings.utils import get_from_env

# Schedule to run column materialization on. Follows crontab syntax.
# Use empty string to prevent from materializing. get_from_env reads an empty value as unset,
# so this one setting goes through os.getenv to keep the disable value.
MATERIALIZE_COLUMNS_SCHEDULE_CRON = os.getenv("MATERIALIZE_COLUMNS_SCHEDULE_CRON", "0 5 * * SAT")
# Minimum query time before a query if considered for optimization by adding materialized columns
MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME = get_from_env("MATERIALIZE_COLUMNS_MINIMUM_QUERY_TIME", 40000, type_cast=int)
# How many hours backwards to look for queries to optimize
MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS = get_from_env(
    "MATERIALIZE_COLUMNS_ANALYSIS_PERIOD_HOURS", 7 * 24, type_cast=int
)
# How big of a timeframe to backfill when materializing event properties. 0 for no backfilling
MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS = get_from_env("MATERIALIZE_COLUMNS_BACKFILL_PERIOD_DAYS", 0, type_cast=int)
# Maximum number of columns to materialize at once. Avoids running into resource bottlenecks (storage + ingest + backfilling).
MATERIALIZE_COLUMNS_MAX_AT_ONCE = get_from_env("MATERIALIZE_COLUMNS_MAX_AT_ONCE", 100, type_cast=int)
