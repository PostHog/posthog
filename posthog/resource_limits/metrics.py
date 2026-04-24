from prometheus_client import Counter

LIMIT_EXCEEDED_COUNTER = Counter(
    "resource_limit_exceeded_total",
    "Count of resource-limit rejections, labelled by limit key and team.",
    labelnames=["limit_key", "team_id"],
)
