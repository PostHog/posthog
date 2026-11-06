"""GitLab egress telemetry.

GitLab documents ``RateLimit-Limit``, ``RateLimit-Remaining``, ``RateLimit-Reset`` (Unix time) and
``RateLimit-Name`` on every response, throttled or not, so the parser reads only those. The headers
show only the most restrictive Rack::Attack throttle; application limits can still answer 429.
"""

import re
from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

# A self-managed instance controls this header, so only a throttle-shaped name becomes a label value.
_THROTTLE_NAME = re.compile(r"[a-z_]{1,64}")

_metrics = EgressMetrics(
    request_counter=Counter(
        "gitlab_api_requests",
        "Number of GitLab API requests made through the GitLab egress client.",
        labelnames=["scope", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "gitlab_api_rate_limit_remaining",
        "Most recently observed GitLab rate limit remaining count.",
        labelnames=["scope", "resource"],
    ),
    limit_gauge=Gauge(
        "gitlab_api_rate_limit_limit",
        "Most recently observed GitLab rate limit.",
        labelnames=["scope", "resource"],
    ),
    reset_gauge=Gauge(
        "gitlab_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed GitLab rate limit reset time as a Unix timestamp.",
        labelnames=["scope", "resource"],
    ),
)


def _throttle_name(headers: Mapping[str, str] | None) -> str:
    name = headers.get("RateLimit-Name") if headers is not None else None
    return name if isinstance(name, str) and _THROTTLE_NAME.fullmatch(name) else "unknown"


def _parse_gitlab_rate_limit(headers: Mapping[str, str] | None, _url: str | None) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        resource=_throttle_name(headers),
        remaining=float_header(headers, "RateLimit-Remaining"),
        limit=float_header(headers, "RateLimit-Limit"),
        reset_at=float_header(headers, "RateLimit-Reset"),
    )


gitlab_egress = EgressObservability(_metrics, _parse_gitlab_rate_limit)
