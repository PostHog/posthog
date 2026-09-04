"""Browserless outbound request telemetry.

Browserless returns no rate-limit headers. Its `X-Response-*` headers describe the page it
fetched, not the API's own budget, so there is nothing to read a remaining count or a reset time
out of, and the snapshot below stays empty rather than inventing one. Volume, status, and latency
are what this domain can honestly report; the gauges exist because the shared metric set declares
them, and they simply stay unset. Verified against the hosted fleet, which returns a bare 200
with no `X-RateLimit-*` and no `Retry-After`.
"""

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.browserless.limiter import BROWSERLESS_DOMAIN
from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

_metrics = EgressMetrics(
    request_counter=Counter(
        "browserless_requests",
        "Outbound Browserless requests.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "browserless_rate_limit_remaining",
        "Unused: Browserless publishes no rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "browserless_rate_limit_limit",
        "Unused: Browserless publishes no rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "browserless_rate_limit_reset_at",
        "Unused: Browserless publishes no rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
)


def _parse_browserless_rate_limit(_response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot(resource="session")


browserless_egress = EgressObservability(BROWSERLESS_DOMAIN, _metrics, _parse_browserless_rate_limit)
register_egress_observability(browserless_egress)


def record_browserless_response(
    response: requests.Response,
    *,
    source: str,
    scope: str,
    method: str,
    endpoint: str,
) -> None:
    browserless_egress.record_response(response, source=source, scope=scope, method=method, endpoint=endpoint)


def record_browserless_exception(*, source: str, scope: str, method: str, endpoint: str, url: str) -> None:
    browserless_egress.record_exception(source=source, scope=scope, method=method, endpoint=endpoint, url=url)
