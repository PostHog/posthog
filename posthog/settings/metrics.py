import os

from posthog.settings.utils import get_from_env
from posthog.utils import str_to_bool

PROMETHEUS_METRICS_EXPORT_PORT = os.getenv("PROMETHEUS_METRICS_EXPORT_PORT", "8001")

# Snuffle (PromQL engine over ClickHouse) the metrics Prometheus read API
# proxies to. Empty disables the endpoint (503) outside local dev.
METRICS_PROMQL_INTERNAL_URL = get_from_env(
    "METRICS_PROMQL_INTERNAL_URL", "http://localhost:9091" if str_to_bool(os.getenv("DEBUG", "False")) else ""
)
METRICS_PROMQL_INTERNAL_BASIC_AUTH = os.getenv("METRICS_PROMQL_INTERNAL_BASIC_AUTH", "")
METRICS_PROMQL_TIMEOUT_SECONDS = float(os.getenv("METRICS_PROMQL_TIMEOUT_SECONDS", "60"))
