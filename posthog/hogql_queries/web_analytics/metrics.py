from prometheus_client import Counter, Histogram

# We use a Histogram rather than Summary because:
# - Histograms expose _sum and _count, enabling server-side average calculations
# - Bucket boundaries allow percentile estimation (p50, p95, p99) without client-side aggregation
# - Buckets are tuned for ClickHouse query latency patterns: most complete in 0.1-10s,
#   tail extends to 120s for cold queries
WEB_ANALYTICS_QUERY_LATENCY_BUCKETS = [
    0.05,
    0.1,
    0.25,
    0.5,
    0.75,
    1.0,
    1.5,
    2.0,
    3.0,
    5.0,
    7.5,
    10.0,
    15.0,
    20.0,
    30.0,
    60.0,
    120.0,
]

WEB_ANALYTICS_QUERY_DURATION = Histogram(
    "web_analytics_query_duration_seconds",
    "Web analytics query execution latency in seconds",
    labelnames=["query_kind", "used_preaggregated", "breakdown", "has_conversion_goal"],
    buckets=WEB_ANALYTICS_QUERY_LATENCY_BUCKETS,
)

WEB_ANALYTICS_QUERY_COUNTER = Counter(
    "web_analytics_query_total",
    "Total number of web analytics queries executed",
    labelnames=["query_kind", "used_preaggregated", "breakdown", "has_conversion_goal"],
)

WEB_ANALYTICS_QUERY_ERRORS = Counter(
    "web_analytics_query_errors_total",
    "Total number of web analytics query errors",
    labelnames=["query_kind", "breakdown", "error_type"],
)
