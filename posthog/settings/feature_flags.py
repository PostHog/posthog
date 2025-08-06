import json
import os
from contextlib import suppress

from posthog.settings.utils import get_list

# The features here are released on the frontend, but the flags are just not yet removed from the code
# WARNING: ONLY the frontend has feature flag overrides. Flags on the backend will NOT be affected by this setting
# Sync with common/storybook/.storybook/decorators/withFeatureFlags.tsx
PERSISTED_FEATURE_FLAGS = [
    *get_list(os.getenv("PERSISTED_FEATURE_FLAGS", "")),
    "simplify-actions",
    "historical-exports-v2",
    "ingestion-warnings-enabled",
    "persons-hogql-query",
    "datanode-concurrency-limit",
    "session-table-property-filters",
    "query-async",
    "artificial-hog",
]

# Per-team local evaluation rate limits, e.g. {"123": "1200/minute", "456": "2400/hour"}
LOCAL_EVAL_RATE_LIMITS: dict[int, str] = {}
with suppress(Exception):
    as_json = json.loads(os.getenv("LOCAL_EVAL_RATE_LIMITS", "{}"))
    LOCAL_EVAL_RATE_LIMITS = {int(k): str(v) for k, v in as_json.items()}
