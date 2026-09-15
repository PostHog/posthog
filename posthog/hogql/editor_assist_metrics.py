from prometheus_client import Counter, Histogram

EDITOR_ASSIST_DURATION_SECONDS = Histogram(
    "hogql_editor_assist_duration_seconds",
    "End-to-end server time of HogQL editor-assist queries (autocomplete and metadata)",
    labelnames=["kind"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LANGUAGE_SERVICE_HTTP_DURATION_SECONDS = Histogram(
    "hogql_language_service_http_duration_seconds",
    "Duration of HTTP requests from Django to the HogQL language service",
    labelnames=["operation"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

LANGUAGE_SERVICE_RESPONSE_SIZE_BYTES = Histogram(
    "hogql_language_service_response_size_bytes",
    "Size of responses from the HogQL language service",
    labelnames=["operation"],
    buckets=(128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144),
)

HOGQL_DATABASE_BUILD_DURATION_SECONDS = Histogram(
    "hogql_database_build_duration_seconds",
    "Duration of HogQL database construction phases",
    labelnames=["phase"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

HOGQL_DATABASE_BUILD_TOTAL = Counter(
    "hogql_database_build",
    "HogQL database builds by the call path that requested them. Redundant builds show up as "
    "executor/printer builds that a shared build should have covered.",
    labelnames=["trigger"],
)
