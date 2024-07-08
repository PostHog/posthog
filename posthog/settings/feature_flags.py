import os

from posthog.settings.utils import get_list

# The features here are released on the frontend, but the flags are just not yet removed from the code
# WARNING: ONLY the frontend has feature flag overrides. Flags on the backend will NOT be affected by this setting
PERSISTED_FEATURE_FLAGS = [
    *get_list(os.getenv("PERSISTED_FEATURE_FLAGS", "")),
    "simplify-actions",
    "historical-exports-v2",
    "ingestion-warnings-enabled",
    "persons-hogql-query",
    "datanode-concurrency-limit",
    "session-table-property-filters",
    "query-async",
]
