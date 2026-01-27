from datetime import timedelta

# ClickHouse query timeout in seconds
# From https://github.com/PostHog/posthog-cloud-infra/blob/master/ansible/config/clickhouse-users.xml#L11
# Keep in sync with the above! And note that this doesn't hold for async queries (which are flagged as of Feb 2023)
CLICKHOUSE_MAX_EXECUTION_TIME = timedelta(seconds=180)

# Default minimum wait time for refreshing an insight
BASE_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=15)
# Wait time for short-term insights
REDUCED_MINIMUM_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=3)
# Wait time for "real-time" insights
REAL_TIME_INSIGHT_REFRESH_INTERVAL = timedelta(minutes=1)
