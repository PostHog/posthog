from posthog.settings.base_variables import TEST
from posthog.settings.utils import get_from_env

USE_PRECALCULATED_CH_COHORT_PEOPLE = not TEST

# Schedules to recalculate cohorts. Follows crontab syntax.
CALCULATE_COHORTS_DAY_SCHEDULE = get_from_env(
    "CALCULATE_COHORTS_DAY_SCHEDULE",
    "*/2 6-17 * * *",
)
CALCULATE_X_PARALLEL_COHORTS_DURING_DAY = get_from_env("CALCULATE_X_PARALLEL_COHORTS_DURING_DAY", 5, type_cast=int)

CALCULATE_COHORTS_NIGHT_SCHEDULE = get_from_env(
    "CALCULATE_COHORTS_NIGHT_SCHEDULE",
    "* 0-5,18-23 * * *",
)
CALCULATE_X_PARALLEL_COHORTS_DURING_NIGHT = get_from_env("CALCULATE_X_PARALLEL_COHORTS_DURING_NIGHT", 5, type_cast=int)

ACTION_EVENT_MAPPING_INTERVAL_SECONDS = get_from_env("ACTION_EVENT_MAPPING_INTERVAL_SECONDS", 300, type_cast=int)

# Schedule to syncronize insight cache states on. Follows crontab syntax.
SYNC_INSIGHT_CACHE_STATES_SCHEDULE = get_from_env(
    "SYNC_INSIGHT_CACHE_STATES_SCHEDULE",
    # Defaults to 5AM UTC on Saturday
    "0 5 * * SAT",
)


UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS = get_from_env(
    "UPDATE_CACHED_DASHBOARD_ITEMS_INTERVAL_SECONDS", 90, type_cast=int
)

COUNT_TILES_WITH_NO_FILTERS_HASH_INTERVAL_SECONDS = get_from_env(
    "COUNT_TILES_WITH_NO_FILTERS_HASH_INTERVAL_SECONDS", 1800, type_cast=int
)

# The query-cache buckets' lifecycle rule (posthog-cloud-infra) garbage-collects S3 blobs after
# this many days. Raising this value needs the bucket rule raised first, or blobs get deleted
# while their Redis pointers still live (see docs/internal/workflows/s3-query-cache-setup.md).
CACHED_RESULTS_TTL_DAYS = 7
CACHED_RESULTS_TTL = CACHED_RESULTS_TTL_DAYS * 24 * 60 * 60

# How long a query stays resolvable by its query ID: the small status record in the app Redis that
# points a finished query at its result in the query cache. Async queries keep it for a day, because
# a browser tab can sit in the background that long before it polls again. A blocking request only
# needs it for the window in which the server can still be finishing a query whose HTTP request
# was dropped, and blocking requests are far more numerous, so theirs is short.
ASYNC_QUERY_STATUS_TTL_SECONDS = 24 * 60 * 60
BLOCKING_QUERY_STATUS_TTL_SECONDS = 15 * 60

# A record that carries the result itself, because the result never reached the query cache, keeps
# a short life. The day-long one is worth its size only while it is a pointer.
INLINE_RESULT_STATUS_TTL_SECONDS = 20 * 60

# A blocking request only gets a record once it has run this long, because only a request the
# ingress could have dropped needs one. Blocking requests are most of the query traffic, so
# recording every one of them would fill the app Redis with records nothing ever reads.
BLOCKING_QUERY_RECORD_AFTER_SECONDS = 60

# TTL for cache entries written by API keys or OAuth clients outside any insight or dashboard.
# retention_ttl in posthog/query_cache/cache.py decides which writes get it.
CACHED_RESULTS_PROGRAMMATIC_TTL = get_from_env("CACHED_RESULTS_PROGRAMMATIC_TTL", 24 * 60 * 60, type_cast=int)

# Per-team cache size limit (default 1GB, can be overridden per-team via Team.extra_settings)
TEAM_CACHE_SIZE_LIMIT_BYTES = get_from_env("TEAM_CACHE_SIZE_LIMIT_BYTES", 1_000_000_000, type_cast=int)

# Schedule to run asynchronous data deletion on. Follows crontab syntax.
# Use empty string to prevent this
CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON = get_from_env(
    "CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON",
    # Defaults to 5AM UTC on Sunday
    "0 5 * * SUN",
)

# Schedule to delete redundant ClickHouse data on. Follows crontab syntax.
# Use empty string to prevent this
CLEAR_CLICKHOUSE_DELETED_PERSON_SCHEDULE_CRON = get_from_env(
    "CLEAR_CLICKHOUSE_REMOVED_DATA_SCHEDULE_CRON",
    # Every third month 5AM UTC on 1st of the month
    "0 5 1 */3 *",
)
