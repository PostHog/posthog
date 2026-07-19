"""Vapi outbound API request telemetry."""

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)
from posthog.egress.vapi.limiter import VAPI_DOMAIN

_metrics = EgressMetrics(
    request_counter=Counter(
        "vapi_api_requests",
        "Outbound Vapi API requests.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "vapi_api_rate_limit_remaining",
        "Last observed Vapi API rate-limit remaining value.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "vapi_api_rate_limit_limit",
        "Last observed Vapi API rate-limit ceiling.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "vapi_api_rate_limit_reset_at",
        "Last observed Vapi API rate-limit reset timestamp.",
        labelnames=["scope", "resource"],
    ),
)


def _parse_vapi_rate_limit(_response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot(resource="api")


vapi_egress = EgressObservability(VAPI_DOMAIN, _metrics, _parse_vapi_rate_limit)
register_egress_observability(vapi_egress)


def record_vapi_api_response(
    response: requests.Response,
    *,
    source: str,
    scope: str,
    method: str,
    endpoint: str,
) -> None:
    vapi_egress.record_response(response, source=source, scope=scope, method=method, endpoint=endpoint)


def record_vapi_api_exception(*, source: str, scope: str, method: str, endpoint: str, url: str) -> None:
    vapi_egress.record_exception(source=source, scope=scope, method=method, endpoint=endpoint, url=url)
