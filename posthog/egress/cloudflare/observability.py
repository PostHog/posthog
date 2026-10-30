"""Cloudflare egress telemetry.

Every Cloudflare call records through ``cloudflare_egress``, so request volume lands on one metric
set whichever subsystem made the call, attributed by the ``source`` label.

Cloudflare documents ``Ratelimit`` and ``Ratelimit-Policy`` headers, but the callers make a few
requests a day at most, so this domain declares no gauges until a caller needs them.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

cloudflare_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "cloudflare_api_requests",
            "Number of Cloudflare API requests made through the Cloudflare egress client.",
            labelnames=["account", "method", "endpoint", "status_code", "source"],
        ),
    )
)
