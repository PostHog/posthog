"""Prometheus metrics of the integration mirror. No label holds a team id, an integration id or a config value."""

from prometheus_client import Counter, Histogram

# Not a service outcome: the task raised before it had one, or the service refused the request.
FAILED = "failed"

MIRROR_ROWS = Counter(
    "integrations_mirror_rows_total",
    "Number of integration rows that the mirror task sent to the credentials service, by kind and outcome.",
    labelnames=["kind", "outcome"],
)
MIRROR_TASK_RETRIES = Counter(
    "integrations_mirror_task_retries_total",
    "Number of times the mirror task scheduled a retry, by reason.",
    labelnames=["reason"],
)
MIRROR_TASK_GIVE_UPS = Counter(
    "integrations_mirror_task_give_ups_total",
    "Number of rows that the mirror task stopped retrying, by reason.",
    labelnames=["reason"],
)
MIRROR_LAG = Histogram(
    "integrations_mirror_lag_seconds",
    "Time from the commit of a Django integration write to the mirror answer for it.",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 300, 900, 3600),
)
