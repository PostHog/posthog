from __future__ import annotations

import os

from prometheus_client import Counter


def get_client_name() -> str:
    return os.environ.get("OTEL_SERVICE_NAME") or "posthog-django"


PERSONHOG_ROUTING_TOTAL = Counter(
    "personhog_routing_total",
    "Tracks which data source was used for each personhog-eligible operation",
    labelnames=["operation", "source", "client_name"],
)

PERSONHOG_ROUTING_ERRORS_TOTAL = Counter(
    "personhog_routing_errors_total",
    "Errors encountered during personhog routing (triggers fallback to ORM)",
    labelnames=["operation", "source", "error_type", "client_name"],
)
