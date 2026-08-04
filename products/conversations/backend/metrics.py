from prometheus_client import Histogram

TICKET_SEARCH_DURATION_SECONDS = Histogram(
    "posthog_support_ticket_search_duration_seconds",
    "End-to-end duration of support ticket list requests that include a search term",
    labelnames=["search_path"],  # ticket_number | text
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, float("inf")),
)
