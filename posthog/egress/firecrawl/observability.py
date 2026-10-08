"""Firecrawl egress telemetry.

Every Firecrawl call records through ``firecrawl_egress``, so request volume lands on one metric set
whichever subsystem made the call, attributed by the ``source`` label.

Firecrawl documents no rate-limit status headers, only ``Retry-After`` on a 429, so this domain
declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

firecrawl_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "firecrawl_api_requests",
            "Number of Firecrawl API requests made through the Firecrawl egress client.",
            labelnames=["account", "method", "endpoint", "status_code", "source"],
        ),
    )
)
