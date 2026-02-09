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

# If updating this, need to look into adding more values to S3 TTLs (see query_cache_s3.py)
CACHED_RESULTS_TTL_DAYS = 7
CACHED_RESULTS_TTL = CACHED_RESULTS_TTL_DAYS * 24 * 60 * 60

# Per-team cache size limit (default 500MB, can be overridden per-team via Team.extra_settings)
TEAM_CACHE_SIZE_LIMIT_BYTES = get_from_env("TEAM_CACHE_SIZE_LIMIT_BYTES", 500 * 1024 * 1024, type_cast=int)

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

# Schedule to count items in playlists. Follows crontab syntax.
PLAYLIST_COUNTER_SCHEDULE_CRON = get_from_env(
    "PLAYLIST_COUNTER_SCHEDULE_CRON",
    # Defaults to every hour at minute 30
    "30 * * * *",
)

# Teams that should process all their cohorts (comma-separated team IDs)
# Example: "2,42" means team 2 and team 42 process all cohorts
REALTIME_COHORT_CALCULATION_TEAMS: set[int] = {
    int(team_id.strip())
    for team_id in get_from_env("REALTIME_COHORT_CALCULATION_TEAMS", "2").split(",")
    if team_id.strip()
}

# Global percentage for teams not in REALTIME_COHORT_CALCULATION_TEAMS (0.0 to 1.0)
# Example: 0.5 means 50% of cohorts for all other teams
REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE: float = get_from_env(
    "REALTIME_COHORT_CALCULATION_GLOBAL_PERCENTAGE", 0.0, type_cast=float
)
