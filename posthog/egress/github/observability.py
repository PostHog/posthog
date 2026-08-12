"""GitHub egress telemetry — the first domain registered with the generic observability mechanism.

Every GitHub API client in the codebase funnels its responses through ``record_github_api_response``
so request volume and GitHub's own ``X-RateLimit-*`` headers land on one metric set, regardless of
which subsystem made the call (installation integration, warehouse source, Visual review,
Conversations, ...). The ``source`` label keeps them apart on a single dashboard.

The metric names are kept stable (``github_integration_api_*``) so existing dashboards stay valid;
the mechanism is the generic :class:`EgressObservability`, so a new outbound API is just another
adapter module like this one.
"""

import re
from collections.abc import Mapping
from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.observability.observability import (
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
        labelnames=["installation_id", "method", "endpoint", "status_code", "source"],
    ),
    # Gauges are keyed by installation_id, not integration_id: GitHub meters the rate limit per App
    # installation, and several PostHog integration rows can share one installation. Keying by the row
    # would split one real budget into flip-flopping per-row series; the installation is the true budget
    # owner. Gauges also carry no source label — all sources sharing an installation update one series.
    remaining_gauge=Gauge(
        "github_integration_api_rate_limit_remaining",
        "Most recently observed GitHub API rate limit remaining count by installation and resource.",
        labelnames=["installation_id", "resource"],
    ),
    limit_gauge=Gauge(
        "github_integration_api_rate_limit_limit",
        "Most recently observed GitHub API rate limit limit by installation and resource.",
        labelnames=["installation_id", "resource"],
    ),
    reset_gauge=Gauge(
        "github_integration_api_rate_limit_reset_timestamp_seconds",
        "Most recently observed GitHub API rate limit reset timestamp by installation and resource.",
        labelnames=["installation_id", "resource"],
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


# A git object id (full or abbreviated SHA). Templated so per-commit URLs (/statuses/{sha},
# /commits/{sha}, git/{blobs,trees,commits}/{sha}) don't each mint a distinct endpoint label.
_SHA_RE = re.compile(r"\A[0-9a-f]{7,40}\Z")

# Path segments whose *next* segment is free-form to the end of the path (a file path or a compare
# ref), so everything after them is collapsed to one placeholder rather than kept verbatim.
_REST_IS_FREEFORM = {"contents": "{path}", "compare": "{refs}"}


def _normalize_github_endpoint(url: str | None) -> str:
    """Collapse a GitHub URL to a low-cardinality endpoint label. Owner/repo, numeric ids, commit
    SHAs, and free-form tails (file paths, compare refs) are templated out — e.g.
    ``.../repos/posthog/posthog/actions/runs/42/jobs`` becomes ``/repos/{owner}/{repo}/actions/runs/{id}/jobs``
    and ``.../repos/o/r/statuses/<sha>`` becomes ``/repos/{owner}/{repo}/statuses/{sha}``.

    The leading-slash, ``{placeholder}`` style matches the curated endpoint strings the installation
    integration passes (e.g. ``/repos/{owner}/{repo}`` in github_integration_base), so the ``endpoint``
    label reads consistently whether it's hand-written or derived from a URL. Without this, callers
    that pass no explicit endpoint (Visual review, warehouse) would emit a unique label per commit
    SHA / branch / file path and blow up Prometheus cardinality — the thing this layer prevents."""
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
        # /contents/<file path...> and /compare/<base>...<head>: the remainder is a single free-form
        # value (and a file path can itself contain slashes), so collapse it and stop.
        if seg in _REST_IS_FREEFORM and i + 1 < len(parts):
            out.extend([seg, _REST_IS_FREEFORM[seg]])
            break
        if seg.isdigit():
            out.append("{id}")
        elif _SHA_RE.match(seg):
            out.append("{sha}")
        else:
            out.append(seg)
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
    installation_id: str | None = None,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Record one GitHub API response. ``installation_id`` is the GitHub App installation — the shared
    rate-limit budget GitHub meters. Pass it when known so the rate-limit gauges are set; identity-blind
    callers (raw PATs) get request volume only. ``source`` attributes the call to a subsystem."""
    github_egress.record_response(response, source=source, scope=installation_id, method=method, endpoint=endpoint)


def record_github_api_exception(
    *,
    source: str,
    method: str,
    endpoint: str | None = None,
    url: str | None = None,
    installation_id: str | None = None,
) -> None:
    """Record a request that raised before a response (timeout, connection error). Pass a curated
    ``endpoint`` or a raw ``url`` (normalised internally)."""
    github_egress.record_exception(source=source, scope=installation_id, method=method, endpoint=endpoint, url=url)
