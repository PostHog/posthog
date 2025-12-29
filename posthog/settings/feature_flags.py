import os
import json
from contextlib import suppress

from posthog.settings.utils import get_from_env, get_list

# Used mostly by the hobby install to have some feature flags enabled by default
# NOTE: This only affects the frontend, the same FFs will still be considered disabled on the backend
PERSISTED_FEATURE_FLAGS = get_list(os.getenv("PERSISTED_FEATURE_FLAGS", ""))

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

# Feature flag cache refresh settings
FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS: int = get_from_env(
    "FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS", 24, type_cast=int
)

# Maximum number of teams to refresh per cache refresh run to prevent memory spikes.
# With ~200k teams, 5000 is a starting point that processes all teams across ~40 runs.
# Run `python manage.py analyze_flags_cache_sizes` to measure actual memory usage.
# Based on typical flag data, 5000 teams ≈ 10-100 MB depending on flag complexity.
# See cache_expiry_manager.py for implementation details.
FLAGS_CACHE_REFRESH_LIMIT: int = get_from_env("FLAGS_CACHE_REFRESH_LIMIT", 5000, type_cast=int)

# Batch size for flags cache verification. Each batch loads both cached data
# (from Redis) and DB data (FeatureFlag objects) into memory simultaneously.
# Teams with 100+ flags and large filters JSONs can use significant memory.
# Reduced from 1000 to 250 to prevent OOM. Decrease further if OOMs persist.
FLAGS_CACHE_VERIFICATION_CHUNK_SIZE: int = get_from_env("FLAGS_CACHE_VERIFICATION_CHUNK_SIZE", 250, type_cast=int)

# Batch size for team metadata cache verification. Team metadata is much smaller
# than flags data, so we can use larger batches without OOM risk.
TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE: int = get_from_env(
    "TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE", 1000, type_cast=int
)
