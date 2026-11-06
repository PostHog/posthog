"""GitLab egress telemetry.

GitLab documents ``RateLimit-Limit``, ``RateLimit-Remaining``, ``RateLimit-Reset`` (Unix time) and
``RateLimit-Name`` on every response, throttled or not, so the parser reads only those. The headers
show only the most restrictive Rack::Attack throttle; application limits can still answer 429.
"""

from collections.abc import Mapping

from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    float_header,
)

# GitLab's documented Rack::Attack throttles. A self-managed instance controls the header, so an
# unlisted value records as "unknown" rather than minting a gauge child per value the server sends.
_THROTTLE_NAMES = frozenset(
    {
        "throttle_authenticated_api",
        "throttle_authenticated_deprecated_api",
        "throttle_authenticated_files_api",
        "throttle_authenticated_git_http",
        "throttle_authenticated_git_lfs",
        "throttle_authenticated_mcp",
        "throttle_authenticated_packages_api",
        "throttle_authenticated_protected_paths_api",
        "throttle_authenticated_protected_paths_web",
        "throttle_authenticated_web",
        "throttle_unauthenticated",
        "throttle_unauthenticated_api",
        "throttle_unauthenticated_deprecated_api",
        "throttle_unauthenticated_files_api",
        "throttle_unauthenticated_git_http",
        "throttle_unauthenticated_packages_api",
        "throttle_unauthenticated_protected_paths",
        "throttle_unauthenticated_web",
    }
)

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
    return name if name in _THROTTLE_NAMES else "unknown"


def _parse_gitlab_rate_limit(headers: Mapping[str, str] | None, _url: str | None) -> RateLimitSnapshot:
    return RateLimitSnapshot(
        resource=_throttle_name(headers),
        remaining=float_header(headers, "RateLimit-Remaining"),
        limit=float_header(headers, "RateLimit-Limit"),
        reset_at=float_header(headers, "RateLimit-Reset"),
    )


gitlab_egress = EgressObservability(_metrics, _parse_gitlab_rate_limit)
