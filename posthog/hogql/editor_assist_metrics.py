from prometheus_client import Counter, Histogram

EDITOR_ASSIST_DURATION_SECONDS = Histogram(
    "hogql_editor_assist_duration_seconds",
    "End-to-end server time of HogQL editor-assist queries (autocomplete and metadata)",
    labelnames=["kind"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
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
