import os

from posthog.settings.utils import get_from_env, str_to_bool

PROMETHEUS_METRICS_EXPORT_PORT = os.getenv("PROMETHEUS_METRICS_EXPORT_PORT", "8001")

# HogQL type-system observability: gate the prepare+typecheck instrumentation and how often it samples.
# Sampling bounds the AST traversal cost; metrics are exposed via the standard Prometheus endpoint.
HOGQL_TYPE_OBSERVABILITY_ENABLED = get_from_env("HOGQL_TYPE_OBSERVABILITY_ENABLED", False, type_cast=str_to_bool)
HOGQL_TYPE_OBSERVABILITY_SAMPLE_RATE = get_from_env("HOGQL_TYPE_OBSERVABILITY_SAMPLE_RATE", 0.0, type_cast=float)
