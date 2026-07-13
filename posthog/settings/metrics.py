import os

PROMETHEUS_METRICS_EXPORT_PORT = os.getenv("PROMETHEUS_METRICS_EXPORT_PORT", "8001")

# OTLP/HTTP push of internal pipeline metrics into the PostHog metrics product
# (the capture-logs /i/v1/metrics ingest, authenticated with a project token).
# Same env contract as the capture-logs and Node.js services; off unless both are set.
OTEL_METRICS_EXPORT_URL = os.getenv("OTEL_METRICS_EXPORT_URL", "")
OTEL_METRICS_EXPORT_TOKEN = os.getenv("OTEL_METRICS_EXPORT_TOKEN", "")
