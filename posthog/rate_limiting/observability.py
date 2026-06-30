"""Generic outbound API egress observability — the metrics analog of the egress limiter.

Mirrors the limiter's shape (:mod:`posthog.rate_limiting.outbound`): a domain-agnostic mechanism,
with each third-party API registered as a *domain* that supplies its own metric set and a parser for
that API's rate-limit response headers. A consumer records a response against a domain; the registered
:class:`EgressObservability` does the rest.

Each domain keeps its own metric names (rather than one shared namespace) so existing dashboards stay
valid and every API can name its metrics idiomatically — the reuse is in the recording mechanism, the
endpoint-normalisation, and the registry, not in a single metric series.
"""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from prometheus_client import Counter, Gauge


@dataclass(frozen=True)
class RateLimitSnapshot:
    """What a domain's parser extracts from one response. Any field may be ``None`` if the API
    didn't report it on this response (e.g. an error before headers were attached)."""

    resource: str = "unknown"
    remaining: float | None = None
    limit: float | None = None
    reset_at: float | None = None


# Parses a response into a RateLimitSnapshot. Per-domain because each API exposes its budget
# differently (GitHub: X-RateLimit-* headers; others may use different headers or a body field).
ResponseParser = Callable[[requests.Response], RateLimitSnapshot]


@dataclass(frozen=True)
class EgressMetrics:
    """The Prometheus instruments one domain records on. The recorder fills labels positionally,
    so a domain's metrics must declare them in this order: the counter as
    ``(<identity>, method, endpoint, status_code, source)`` and each gauge as
    ``(<identity>, resource, source)``. ``<identity>`` is whatever the domain calls the budget
    owner (GitHub names it ``integration_id``); the recorder fills it from the ``scope`` argument."""

    request_counter: Counter
    remaining_gauge: Gauge
    limit_gauge: Gauge
    reset_gauge: Gauge


def default_normalize_endpoint(url: str | None) -> str:
    """Collapse a URL path to a low-cardinality endpoint label by templating out numeric ids.
    Domains with structured paths (e.g. GitHub's owner/repo) can pass their own normaliser."""
    if not url:
        return "unknown"
    path = urlparse(url).path.strip("/")
    if not path:
        return "/"
    return "/".join(":id" if seg.isdigit() else seg for seg in path.split("/"))


class EgressObservability:
    """One third-party API's egress telemetry: a metric set, a response parser, and an endpoint
    normaliser. Construct one per domain and register it; consumers record through it.

    ``scope`` is the budget owner's identity (e.g. a GitHub installation/integration id). The request
    counter is always incremented; the rate-limit gauges are only set when a ``scope`` is given, since
    a last-observed gauge is meaningless when many owners alias onto one empty label.
    """

    def __init__(
        self,
        domain: str,
        metrics: EgressMetrics,
        parser: ResponseParser,
        endpoint_normalizer: Callable[[str | None], str] = default_normalize_endpoint,
    ) -> None:
        self.domain = domain
        self._metrics = metrics
        self._parser = parser
        self._normalize_endpoint = endpoint_normalizer

    def record_response(
        self,
        response: requests.Response,
        *,
        source: str,
        scope: str | None = None,
        method: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        method_label = (method or getattr(response.request, "method", None) or "GET").upper()
        endpoint_label = (
            endpoint if endpoint is not None else self._normalize_endpoint(getattr(response.request, "url", None))
        )
        self._metrics.request_counter.labels(
            scope or "", method_label, endpoint_label, str(response.status_code), source
        ).inc()

        if scope is None:
            return

        snapshot = self._parser(response)
        if snapshot.remaining is not None:
            self._metrics.remaining_gauge.labels(scope, snapshot.resource, source).set(snapshot.remaining)
        if snapshot.limit is not None:
            self._metrics.limit_gauge.labels(scope, snapshot.resource, source).set(snapshot.limit)
        if snapshot.reset_at is not None:
            self._metrics.reset_gauge.labels(scope, snapshot.resource, source).set(snapshot.reset_at)

    def record_exception(self, *, source: str, method: str, endpoint: str, scope: str | None = None) -> None:
        """Record a request that raised before a response (timeout, connection error)."""
        # Uppercase to match record_response, so a method never splits into two series by case.
        self._metrics.request_counter.labels(scope or "", method.upper(), endpoint, "exception", source).inc()


_REGISTRY: dict[str, EgressObservability] = {}


def register_egress_observability(observability: EgressObservability) -> None:
    _REGISTRY[observability.domain] = observability


def resolve_egress_observability(domain: str) -> EgressObservability:
    obs = _REGISTRY.get(domain)
    if obs is None:
        raise ValueError(
            f"No egress observability registered for domain '{domain}'; "
            "register one with register_egress_observability() before recording against it"
        )
    return obs


def record_outbound_api_response(
    response: requests.Response,
    *,
    domain: str,
    source: str,
    scope: str | None = None,
    method: str | None = None,
    endpoint: str | None = None,
) -> None:
    """Domain-keyed convenience for generic callers that hold only a domain string."""
    resolve_egress_observability(domain).record_response(
        response, source=source, scope=scope, method=method, endpoint=endpoint
    )
