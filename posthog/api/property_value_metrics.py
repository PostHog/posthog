from prometheus_client import Histogram

PROPERTY_VALUES_DURATION = Histogram(
    "posthog_property_values_request_duration_seconds",
    "Duration of property value lookup requests",
    labelnames=["endpoint_type"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
