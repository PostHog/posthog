"""logo.dev egress telemetry.

Every logo.dev call records through ``logodev_egress``, so request volume lands on one metric set
whichever subsystem made the call (CDP icon picker, MCP store icons, ...), attributed by the
``source`` label. logo.dev reports no rate-limit response headers, so this domain declares no gauges.
"""

from urllib.parse import urlparse

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

_metrics = EgressMetrics(
    request_counter=Counter(
        "logodev_api_requests",
        "Number of logo.dev API requests made through the logo.dev egress client.",
        labelnames=["account", "method", "endpoint", "status_code", "source"],
    ),
)


def _normalize_logodev_endpoint(url: str | None) -> str:
    """Collapse a logo.dev URL to a low-cardinality endpoint label. ``img.logo.dev/{brand-domain}``
    would otherwise mint one label per brand, so the brand path is templated to ``/img/{domain}``;
    the search API's fixed path is kept verbatim."""
    if not url:
        return "unknown"
    parsed = urlparse(url)
    if parsed.netloc == "img.logo.dev":
        return "/img/{domain}"
    path = parsed.path.rstrip("/")
    return path or "/"


logodev_egress = EgressObservability(_metrics, endpoint_normalizer=_normalize_logodev_endpoint)
