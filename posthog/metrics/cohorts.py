"""
Cohort calculation performance metrics.

This module contains Prometheus metrics for monitoring cohort calculation performance.
It's kept lightweight to avoid import side-effects in both Celery and Temporal processes.
"""

from prometheus_client import Histogram

# Cohort calculation timing histograms
COHORT_CALCULATION_TOTAL_DURATION_HISTOGRAM = Histogram(
    "cohort_calculation_total_duration_seconds",
    "Total duration of cohort calculation from start to finish",
    ["percentile_bucket"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, float("inf")),
)

COHORT_QUERY_EXECUTION_DURATION_HISTOGRAM = Histogram(
    "cohort_query_execution_duration_seconds",
    "Duration of ClickHouse query execution for cohort calculation",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
)

COHORT_DURATION_UPDATE_HISTOGRAM = Histogram(
    "cohort_duration_update_seconds",
    "Duration of updating cohort duration in database",
    ["percentile_bucket"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, float("inf")),
)
