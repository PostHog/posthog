PROPERTY_MATH_FUNCTIONS = {
    "sum": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "median": "quantile(0.50)",
    "p75": "quantile(0.75)",
    "p90": "quantile(0.90)",
    "p95": "quantile(0.95)",
    "p99": "quantile(0.99)",
}

COUNT_PER_ACTOR_MATH_FUNCTIONS = {
    "avg_count_per_actor": "avg",
    "min_count_per_actor": "min",
    "max_count_per_actor": "max",
    "median_count_per_actor": "quantile(0.50)",
    "p75_count_per_actor": "quantile(0.75)",
    "p90_count_per_actor": "quantile(0.90)",
    "p95_count_per_actor": "quantile(0.95)",
    "p99_count_per_actor": "quantile(0.99)",
}

ALL_SUPPORTED_MATH_FUNCTIONS = [
    *list(PROPERTY_MATH_FUNCTIONS.keys()),
    *list(COUNT_PER_ACTOR_MATH_FUNCTIONS.keys()),
]
