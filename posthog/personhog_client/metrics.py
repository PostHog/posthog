from __future__ import annotations

from django.conf import settings

from prometheus_client import Counter


def get_client_name() -> str:
    return getattr(settings, "OTEL_SERVICE_NAME", None) or "posthog-django"


PERSONHOG_ROUTING_TOTAL = Counter(
    "personhog_routing_total",
    "Tracks which data source was used for each personhog-eligible operation",
    labelnames=["operation", "source", "client_name"],
)

PERSONHOG_ROUTING_ERRORS_TOTAL = Counter(
    "personhog_routing_errors_total",
    "Errors encountered during personhog routing",
    labelnames=["operation", "source", "error_type", "client_name"],
)

PERSONHOG_TEAM_MISMATCH_TOTAL = Counter(
    "personhog_team_mismatch_total",
    "Persons dropped because personhog returned a mismatched team_id",
    labelnames=["operation", "client_name"],
)

PERSONHOG_ERRORS_TOTAL = Counter(
    "personhog_errors_total",
    "Total PersonHog gRPC errors — every failed gRPC attempt",
    labelnames=["method", "client", "error_type"],
)

PERSONHOG_RETRIES_TOTAL = Counter(
    "personhog_retries_total",
    "Total PersonHog gRPC retries before success or exhaustion",
    labelnames=["method", "client", "error_type"],
)

PERSONHOG_TERMINAL_ERRORS_TOTAL = Counter(
    "personhog_terminal_errors_total",
    "PersonHog gRPC errors after retry exhaustion — the request was not fulfilled",
    labelnames=["method", "client", "error_type"],
)
