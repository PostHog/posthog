"""Composio outbound API request telemetry."""

from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge

from posthog.egress.composio.limiter import COMPOSIO_DOMAIN
from posthog.egress.observability.observability import (
    EgressMetrics,
    EgressObservability,
    RateLimitSnapshot,
    register_egress_observability,
)

_metrics = EgressMetrics(
    request_counter=Counter(
        "composio_api_requests",
        "Outbound Composio API requests.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
    remaining_gauge=Gauge(
        "composio_api_rate_limit_remaining",
        "Last observed Composio API rate-limit remaining value.",
        labelnames=["account", "resource"],
    ),
    limit_gauge=Gauge(
        "composio_api_rate_limit_limit",
        "Last observed Composio API rate-limit ceiling.",
        labelnames=["account", "resource"],
    ),
    reset_gauge=Gauge(
        "composio_api_rate_limit_reset_at",
        "Last observed Composio API rate-limit reset timestamp.",
        labelnames=["account", "resource"],
    ),
)

# Path segments that are opaque per-object ids rather than route names. Composio's nano-ids carry
# a type prefix (ca_ connected account, ac_ auth config); session ids and UUIDs carry none, so
# length and shape decide those.
_ID_PREFIXES = ("ca_", "ac_", "cs_", "ti_")


def _is_id_segment(segment: str) -> bool:
    if segment.isdigit():
        return True
    if segment.startswith(_ID_PREFIXES):
        return True
    # Opaque ids are long and mix cases or digits; route names are lowercase words and underscores.
    return len(segment) >= 16 and any(c.isdigit() or c.isupper() for c in segment)


def normalize_composio_endpoint(url: str | None) -> str:
    """Template per-object ids out of a Composio path so the endpoint label stays low-cardinality."""
    if not url:
        return "unknown"
    path = urlparse(url).path.strip("/")
    if not path:
        return "/"
    return "/" + "/".join("{id}" if _is_id_segment(segment) else segment for segment in path.split("/"))


def _parse_composio_rate_limit(response: requests.Response) -> RateLimitSnapshot:
    """Composio does not document its rate-limit headers, so read the conventional ones when they
    are present and report nothing when they are not. The gauges simply stay unset in that case."""
    headers = getattr(response, "headers", None) or {}

    def _number(name: str) -> float | None:
        raw = headers.get(name)
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return RateLimitSnapshot(
        resource="api",
        remaining=_number("x-ratelimit-remaining"),
        limit=_number("x-ratelimit-limit"),
        reset_at=_number("x-ratelimit-reset"),
    )


composio_egress = EgressObservability(
    COMPOSIO_DOMAIN, _metrics, _parse_composio_rate_limit, normalize_composio_endpoint
)
register_egress_observability(composio_egress)


def record_composio_api_response(
    response: requests.Response,
    *,
    source: str,
    account: str,
    method: str,
    endpoint: str,
) -> None:
    composio_egress.record_response(response, source=source, scope=account, method=method, endpoint=endpoint)


def record_composio_api_exception(*, source: str, account: str, method: str, endpoint: str, url: str) -> None:
    composio_egress.record_exception(source=source, scope=account, method=method, endpoint=endpoint, url=url)
