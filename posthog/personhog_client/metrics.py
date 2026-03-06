from __future__ import annotations

from prometheus_client import Counter

PERSONHOG_ROUTING_TOTAL = Counter(
    "personhog_routing_total",
    "Tracks which data source was used for each personhog-eligible operation",
    labelnames=["operation", "source"],
)

PERSONHOG_ROUTING_ERRORS_TOTAL = Counter(
    "personhog_routing_errors_total",
    "Errors encountered during personhog routing (triggers fallback to ORM)",
    labelnames=["operation", "source", "error_type"],
)
