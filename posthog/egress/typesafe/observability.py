"""TypeSafe egress telemetry.

Every TypeSafe call records through ``typesafe_egress``, so request volume lands on one metric set
whichever subsystem made the call, attributed by the ``source`` label.

TypeSafe documents no rate-limit status headers, only ``retry-after`` on some 429s, so this domain
declares no gauges.
"""

from prometheus_client import Counter

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

typesafe_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "typesafe_api_requests",
            "Number of TypeSafe API requests made through the TypeSafe egress client.",
            labelnames=["account", "method", "endpoint", "status_code", "source"],
        ),
    )
)
