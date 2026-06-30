"""GitHub egress telemetry — the first domain registered with the generic observability mechanism.

Every GitHub API client in the codebase funnels its responses through ``record_github_api_response``
so request volume and GitHub's own ``X-RateLimit-*`` headers land on one metric set, regardless of
which subsystem made the call (installation integration, warehouse source, Visual review,
Conversations, ...). The ``source`` label keeps them apart on a single dashboard.

The metric names are kept stable (``github_integration_api_*``) so existing dashboards stay valid;
the mechanism is the generic :class:`EgressObservability`, so a new outbound API is just another
adapter module like this one.
"""

from collections.abc import Mapping
from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge

from posthog.rate_limiting.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

GITHUB_DOMAIN = "github"

_metrics = EgressMetrics(
    request_counter=Counter(
        "github_integration_api_requests",
        "Number of GitHub API requests made through a GitHub client.",
        labelnames=["integration_id", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "github_integration_api_rate_limit_remaining",
        "Most recently observed GitHub API rate limit remaining count by integration and resource.",
        labelnames=["integration_id", "resource", "source"],
    ),
    limit_gauge=Gauge(
        "github_integration_api_rate_limit_limit",
        "Most recently observed GitHub API rate limit limit by integration and resource.",
        labelnames=["integration_id", "resource", "source"],
    ),
    reset_gauge=Gauge(
        "github_integration_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed GitHub API rate limit reset timestamp by integration and resource.",
        labelnames=["integration_id", "resource", "source"],
    ),
)


def _float_header(headers: Mapping[str, str] | None, name: str) -> float | None:
    if headers is None:
        return None
    value = headers.get(name)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_github_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    headers = response.headers if isinstance(response.headers, Mapping) else None
    return RateLimitSnapshot(
        resource=headers.get("X-RateLimit-Resource", "unknown") if headers is not None else "unknown",
        remaining=_float_header(headers, "X-RateLimit-Remaining"),
        limit=_float_header(headers, "X-RateLimit-Limit"),
        reset_at=_float_header(headers, "X-RateLimit-Reset"),
    )


def _normalize_github_endpoint(url: str | None) -> str:
    """Collapse a GitHub URL to a low-cardinality endpoint label. Owner/repo and numeric ids are
    templated out — e.g. ``.../repos/posthog/posthog/actions/runs/42/jobs`` becomes
    ``/repos/{owner}/{repo}/actions/runs/{id}/jobs``.

    The leading-slash, ``{placeholder}`` style matches the curated endpoint strings the installation
    integration passes (e.g. ``/repos/{owner}/{repo}`` in github_integration_base), so the ``endpoint``
    label reads consistently whether it's hand-written or derived from a URL."""
    if not url:
        return "unknown"
    path = urlparse(url).path.strip("/")
    if not path:
        return "/"
    parts = path.split("/")
    out: list[str] = []
    i = 0
    while i < len(parts):
        seg = parts[i]
        # "/repos/{owner}/{repo}/..." — the two segments after "repos" are always owner+repo.
        if seg == "repos" and i + 2 < len(parts):
            out.extend(["repos", "{owner}", "{repo}"])
            i += 3
            continue
        out.append("{id}" if seg.isdigit() else seg)
        i += 1
    return "/" + "/".join(out)


github_egress = EgressObservability(
    GITHUB_DOMAIN, _metrics, _parse_github_rate_limit, endpoint_normalizer=_normalize_github_endpoint
)
register_egress_observability(github_egress)


def record_github_api_response(
    response: requests.Response,
    *,
    source: str,
    integration_id: str | None = None,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Record one GitHub API response. ``integration_id`` is the budget owner; pass it when known so
    the per-integration rate-limit gauges are set (identity-blind callers get request volume only)."""
    github_egress.record_response(response, source=source, scope=integration_id, method=method, endpoint=endpoint)


def record_github_api_exception(
    *,
    source: str,
    method: str,
    endpoint: str,
    integration_id: str | None = None,
) -> None:
    """Record a request that raised before a response (timeout, connection error)."""
    github_egress.record_exception(source=source, scope=integration_id, method=method, endpoint=endpoint)
