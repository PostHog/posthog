"""Vercel egress telemetry.

Every call to the Vercel API records through ``vercel_egress``, attributed by the ``source`` label.
Vercel documents no rate-limit response headers, so this domain declares no gauges.
"""

from urllib.parse import urlparse

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

# The segment after each of these is an identifier: an installation, a resource, a flag key, an invoice.
_ID_PARENT_SEGMENTS = frozenset({"installations", "resources", "items", "invoices"})


def normalize_vercel_endpoint(url: str | None) -> str:
    if not url:
        return "unknown"
    segments = urlparse(url).path.strip("/").split("/")
    if segments == [""]:
        return "/"
    templated = [
        "{id}" if segment.isdigit() or (index > 0 and segments[index - 1] in _ID_PARENT_SEGMENTS) else segment
        for index, segment in enumerate(segments)
    ]
    return "/" + "/".join(templated)


vercel_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "vercel_api_requests",
            "Number of Vercel API requests made through the Vercel egress client.",
            labelnames=["installation", "method", "endpoint", "status_code", "source"],
        ),
    ),
    endpoint_normalizer=normalize_vercel_endpoint,
)
