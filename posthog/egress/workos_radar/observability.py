"""WorkOS Radar egress telemetry.

Every Radar call records through ``workos_radar_egress``, so request volume lands on one metric set
whichever flow made the call, attributed by the ``source`` label.

WorkOS documents no rate-limit status headers, only ``Retry-After`` on some 429 responses, so this
domain declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

workos_radar_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "workos_radar_api_requests",
            "Number of WorkOS Radar API requests made through the Radar egress client.",
            labelnames=["api_key", "method", "endpoint", "status_code", "source"],
        ),
    )
)
