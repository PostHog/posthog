from prometheus_client import Counter, Gauge, Histogram

SYNC_TEAMS = Counter(
    "customer_analytics_membership_sync_teams_total", "Membership registry sync outcomes", ["outcome", "dry_run"]
)
SYNC_LAG = Gauge("customer_analytics_membership_sync_lag_seconds", "Oldest unfinished activation in a coordinator page")
CHUNK_DURATION = Histogram(
    "customer_analytics_membership_chunk_duration_seconds", "Membership backfill activity duration"
)
