"""Generic outbound API egress observability — the metrics analog of the egress limiter.

Mirrors the limiter's shape (:mod:`posthog.egress.limiter.outbound`): a domain-agnostic mechanism,
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
    ``(<scope>, method, endpoint, status_code, source)`` and each gauge as ``(<scope>, resource)``.

    ``<scope>`` is the rate-limit budget owner in the *domain's own* id space — for GitHub the App
    ``installation_id`` (what GitHub actually meters), never a PostHog DB row id. Keeping the identity in
    the external API's namespace is what lets one shared budget map to one series: several PostHog
    integration rows can share a GitHub installation, and they must all land on the same gauge, otherwise
    one real budget splits into N flip-flopping per-row series. The recorder fills ``<scope>`` from the
    ``scope`` argument; per-caller attribution is the ``source`` label's job, not the identity's.

    The gauges deliberately carry no ``source``: the budget is shared across sources, so all sources must
    update one series per (scope, resource). Labeling gauges by source would strand a stale last-observed
    value per source after that source goes quiet, misreporting remaining budget."""

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
    return "/" + "/".join("{id}" if seg.isdigit() else seg for seg in path.split("/"))


class EgressObservability:
    """One third-party API's egress telemetry: a metric set, a response parser, and an endpoint
    normaliser. Construct one per domain and register it; consumers record through it.

    ``scope`` is the rate-limit budget owner in the domain's own id space (e.g. a GitHub App installation
    id, which several PostHog integrations can share) — not a PostHog DB row id. The counter is always
    incremented; the gauges are only set when a ``scope`` is given, since a last-observed gauge is
    meaningless when many owners alias onto one empty label.
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
        # The response's .request (and its method/url) may be absent or non-string — a response built
        # without a prepared request, or a test mock whose attributes are themselves Mocks. Coerce to
        # str-or-None so a recorder never raises into the request flow: telemetry is best-effort, and a
        # urlparse(Mock) blowing up here must not fail the actual GitHub call.
        request = getattr(response, "request", None)
        req_method = getattr(request, "method", None)
        req_url = getattr(request, "url", None)
        method_label = (method or (req_method if isinstance(req_method, str) else None) or "GET").upper()
        endpoint_label = (
            endpoint
            if endpoint is not None
            else self._normalize_endpoint(req_url if isinstance(req_url, str) else None)
        )
        self._metrics.request_counter.labels(
            scope or "", method_label, endpoint_label, str(response.status_code), source
        ).inc()

        if scope is None:
            return

        # Gauges are keyed by (scope, resource) only — the shared budget owner, no source. Every
        # source sharing one budget updates one series; a per-source gauge would strand stale values.
        snapshot = self._parser(response)
        if snapshot.remaining is not None:
            self._metrics.remaining_gauge.labels(scope, snapshot.resource).set(snapshot.remaining)
        if snapshot.limit is not None:
            self._metrics.limit_gauge.labels(scope, snapshot.resource).set(snapshot.limit)
        if snapshot.reset_at is not None:
            self._metrics.reset_gauge.labels(scope, snapshot.resource).set(snapshot.reset_at)

    def record_exception(
        self,
        *,
        source: str,
        method: str,
        endpoint: str | None = None,
        url: str | None = None,
        scope: str | None = None,
    ) -> None:
        """Record a request that raised before a response (timeout, connection error). Pass a pre-normalised
        ``endpoint`` or a raw ``url`` (normalised here via the domain's normaliser) — mirrors record_response,
        so a caller that only holds a URL doesn't need the domain's normaliser."""
        endpoint_label = endpoint if endpoint is not None else self._normalize_endpoint(url)
        # Uppercase to match record_response, so a method never splits into two series by case.
        self._metrics.request_counter.labels(scope or "", method.upper(), endpoint_label, "exception", source).inc()


# Limiter admission decisions, domain-labeled like everything else here. Counter (not gauge) so the
# grant/deny rate per domain+source+priority is visible — that's how you see deferrable BATCH traffic
# being shed before CRITICAL as a shared budget fills. ``granted`` is "true"/"false"; prometheus_client
# appends ``_total`` to the exposed series name.
outbound_rate_limit_decisions = Counter(
    "outbound_rate_limit_decisions",
    "Outbound egress rate limiter admission decisions. Recorded per attempt, so a shed call that retries "
    "(e.g. warehouse _fetch_page under tenacity) inflates granted=false by the retry count — alert on the "
    "grant/deny ratio or rate, not raw denied totals.",
    labelnames=["domain", "source", "priority", "granted"],
)


def record_outbound_decision(*, domain: str, source: str, priority: str, granted: bool) -> None:
    """Record one limiter decision. ``priority`` is the lane string (e.g. ``"batch"``); the caller
    derives ``domain`` from the limiter key's first segment so this stays limiter-library-agnostic."""
    outbound_rate_limit_decisions.labels(domain, source, priority, "true" if granted else "false").inc()


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
