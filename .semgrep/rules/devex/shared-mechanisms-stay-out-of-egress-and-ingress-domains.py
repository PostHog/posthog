# Test cases for shared-mechanisms-stay-out-of-egress-and-ingress-domains rule.
# ruff: noqa: F401, F841
import requests
from prometheus_client import Counter, Gauge, Histogram

# ruleid: shared-mechanisms-stay-out-of-egress-and-ingress-domains
from opentelemetry import trace

from posthog.egress.observability.observability import EgressMetrics, EgressObservability

tracer = trace.get_tracer(__name__)

# ruleid: shared-mechanisms-stay-out-of-egress-and-ingress-domains
_request_duration = Histogram("vendor_api_request_duration_seconds", "Request duration.", labelnames=["endpoint"])

# ruleid: shared-mechanisms-stay-out-of-egress-and-ingress-domains
_retries = Counter("vendor_api_retries", "Retries.", labelnames=["endpoint"])

# ok: shared-mechanisms-stay-out-of-egress-and-ingress-domains
vendor_egress = EgressObservability(
    EgressMetrics(
        request_counter=Counter(
            "vendor_api_requests",
            "Requests.",
            labelnames=["scope", "method", "endpoint", "status_code", "source"],
        ),
        remaining_gauge=Gauge("vendor_api_rate_limit_remaining", "Remaining.", labelnames=["scope", "resource"]),
    )
)


def traced_request(url: str) -> requests.Response:
    # ruleid: shared-mechanisms-stay-out-of-egress-and-ingress-domains
    with tracer.start_as_current_span("vendor.http.request"):
        return requests.get(url)


# One-off: only this vendor reports a Retry-After.
# ok: shared-mechanisms-stay-out-of-egress-and-ingress-domains
# nosemgrep: shared-mechanisms-stay-out-of-egress-and-ingress-domains
_retry_at = Gauge("vendor_api_retry_at", "Retry-After.", labelnames=["scope"])
