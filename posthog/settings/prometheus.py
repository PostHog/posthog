from prometheus_client import Counter

RATE_LIMIT_EXCEEDED_COUNTER = Counter(
    "rate_limit_exceeded_total",
    "Dropped requests due to rate-limiting, per team_id, scope and path.",
    labelnames=["team_id", "scope", "path"],
)

RATE_LIMIT_BYPASSED_COUNTER = Counter(
    "rate_limit_bypassed_total",
    "Requests that should be dropped by rate-limiting but allowed by configuration.",
    labelnames=["team_id", "path"],
)
