import os
import json
from contextlib import suppress

from posthog.settings.utils import get_from_env, get_list

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
    "recordings-blobby-v2-replay",
    "use-blob-v2-lts",
]

# Per-team local evaluation rate limits, e.g. {"123": "1200/minute", "456": "2400/hour"}
LOCAL_EVAL_RATE_LIMITS: dict[int, str] = {}
with suppress(Exception):
    as_json = json.loads(os.getenv("LOCAL_EVAL_RATE_LIMITS", "{}"))
    LOCAL_EVAL_RATE_LIMITS = {int(k): str(v) for k, v in as_json.items()}

# Per-team remote config rate limits, e.g. {"123": "1200/minute", "456": "2400/hour"}
REMOTE_CONFIG_RATE_LIMITS: dict[int, str] = {}
with suppress(Exception):
    as_json = json.loads(os.getenv("REMOTE_CONFIG_RATE_LIMITS", "{}"))
    REMOTE_CONFIG_RATE_LIMITS = {int(k): str(v) for k, v in as_json.items()}

# Feature flag last_called_at sync settings
FEATURE_FLAG_LAST_CALLED_AT_SYNC_BATCH_SIZE: int = get_from_env(
    "FEATURE_FLAG_LAST_CALLED_AT_SYNC_BATCH_SIZE", 1000, type_cast=int
)
FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT: int = get_from_env(
    "FEATURE_FLAG_LAST_CALLED_AT_SYNC_CLICKHOUSE_LIMIT", 100000, type_cast=int
)
FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS: int = get_from_env(
    "FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS", 1, type_cast=int
)
