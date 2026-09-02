import requests
from prometheus_client import Counter, Gauge

from posthog.egress.google_workspace.limiter import GOOGLE_WORKSPACE_DOMAIN
from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

_metrics = EgressMetrics(
    request_counter=Counter(
        "google_workspace_api_requests",
        "Outbound Google Workspace API requests.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "google_workspace_api_rate_limit_remaining",
        "Last observed Google Workspace API rate-limit remaining value.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "google_workspace_api_rate_limit_limit",
        "Last observed Google Workspace API rate-limit ceiling.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "google_workspace_api_rate_limit_reset_at",
        "Last observed Google Workspace API rate-limit reset timestamp.",
        labelnames=["scope", "resource"],
    ),
)


def _parse_google_workspace_rate_limit(_response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot(resource="api")


google_workspace_egress = EgressObservability(
    GOOGLE_WORKSPACE_DOMAIN,
    _metrics,
    _parse_google_workspace_rate_limit,
)
register_egress_observability(google_workspace_egress)


def record_google_workspace_api_response(
    response: requests.Response,
    *,
    source: str,
    account_id: str,
    method: str,
    endpoint: str,
) -> None:
    google_workspace_egress.record_response(
        response,
        source=source,
        scope=account_id,
        method=method,
        endpoint=endpoint,
    )


def record_google_workspace_api_exception(
    *,
    source: str,
    account_id: str,
    method: str,
    endpoint: str,
    url: str,
) -> None:
    google_workspace_egress.record_exception(
        source=source,
        scope=account_id,
        method=method,
        endpoint=endpoint,
        url=url,
    )
