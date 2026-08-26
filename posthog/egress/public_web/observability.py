import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

PUBLIC_WEB_DOMAIN = "public_web"

_metrics = EgressMetrics(
    request_counter=Counter(
        "public_web_requests",
        "Number of bounded public-web requests made through the public-web egress client.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "public_web_rate_limit_remaining",
        "Unused placeholder for public-web provider rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "public_web_rate_limit_limit",
        "Unused placeholder for public-web provider rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "public_web_rate_limit_reset_timestamp_seconds",
        "Unused placeholder for public-web provider rate-limit headers.",
        labelnames=["scope", "resource"],
    ),
)


def _parse_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    return RateLimitSnapshot()


public_web_egress = EgressObservability(PUBLIC_WEB_DOMAIN, _metrics, _parse_rate_limit)
register_egress_observability(public_web_egress)


def record_public_web_response(response: requests.Response, *, source: str, method: str, endpoint: str) -> None:
    public_web_egress.record_response(response, source=source, method=method, endpoint=endpoint)


def record_public_web_exception(*, source: str, method: str, endpoint: str, url: str) -> None:
    public_web_egress.record_exception(source=source, method=method, endpoint=endpoint, url=url)
