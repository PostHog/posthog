import os
import json
from contextlib import suppress

from posthog.settings.access import SECRET_KEY
from posthog.settings.base_variables import TEST
from posthog.settings.utils import get_from_env, get_list, get_set, str_to_bool

# Used mostly by the hobby install to have some feature flags enabled by default
# NOTE: This only affects the frontend, the same FFs will still be considered disabled on the backend
PERSISTED_FEATURE_FLAGS = get_list(os.getenv("PERSISTED_FEATURE_FLAGS", ""))

# Encryption keys for remote-config feature flag payloads, kept separate from
# Temporal's keys (posthog/settings/temporal.py) so the two rotate independently.
# An ordered list: the first key encrypts new payloads, every key can decrypt. That
# is what lets us rotate without a hard cutover: prepend a new key, re-encrypt existing
# payloads (manage.py reencrypt_flag_payloads), then drop the old key. Defaults to
# [SECRET_KEY] so self-hosted installs, which encrypt flag payloads with SECRET_KEY,
# keep working with no configuration. An empty or unset value floors to [SECRET_KEY]
# so a key is always present.
FLAGS_SECRET_KEYS: list[str] = get_list(os.getenv("FLAGS_SECRET_KEYS", "")) or [SECRET_KEY]

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
FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS: int = min(
    get_from_env("FEATURE_FLAG_LAST_CALLED_AT_SYNC_LOOKBACK_DAYS", 1, type_cast=int),
    6,  # events_recent has 7-day TTL; cap with 1-day margin
)
FEATURE_FLAG_LAST_CALLED_AT_SYNC_CHUNK_MINUTES: int = max(
    1,
    get_from_env("FEATURE_FLAG_LAST_CALLED_AT_SYNC_CHUNK_MINUTES", 5, type_cast=int),
)
# MAX_LOOKBACK_HOURS caps how far back a stale/missing checkpoint can reach.
# With the defaults (LOOKBACK_DAYS=1 → 24h, MAX_LOOKBACK_HOURS=6), the
# effective lookback is 6h. LOOKBACK_DAYS only has effect when
# LOOKBACK_DAYS × 24 ≤ MAX_LOOKBACK_HOURS; otherwise it is capped.
FEATURE_FLAG_LAST_CALLED_AT_SYNC_MAX_LOOKBACK_HOURS: int = max(
    1,
    get_from_env("FEATURE_FLAG_LAST_CALLED_AT_SYNC_MAX_LOOKBACK_HOURS", 6, type_cast=int),
)
# The sync reads distributed_events_recent, which either replica of the batch-export shard can
# answer, so rows inserted moments ago may be missing from whichever one serves a given query.
# Ending the scan window this far before now keeps the checkpoint from advancing past those
# rows, so a row still missing at read time is picked up by the next run instead of being
# skipped for good.
FEATURE_FLAG_LAST_CALLED_AT_SYNC_REPLICATION_BUFFER_SECONDS: int = max(
    0,
    get_from_env("FEATURE_FLAG_LAST_CALLED_AT_SYNC_REPLICATION_BUFFER_SECONDS", 60, type_cast=int),
)
# Per-chunk ClickHouse execution cap. sync_execute sets no max_execution_time of its own, so
# without this a hung query is bounded only by the server profile, and a run can outlive the
# 30-minute lock that stops two of these from overlapping. Prod chunks take a few seconds each
# and whole runs peak under two minutes, so this only trips on a genuine hang.
FEATURE_FLAG_LAST_CALLED_AT_SYNC_QUERY_TIMEOUT_SECONDS: int = max(
    1,
    get_from_env("FEATURE_FLAG_LAST_CALLED_AT_SYNC_QUERY_TIMEOUT_SECONDS", 120, type_cast=int),
)

# Refresh sweep settings for the `flags` cache; `flag_definitions` has its own pair below.
FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS: int = get_from_env(
    "FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS", 24, type_cast=int
)

# Maximum number of teams the `flags` sweep takes per run. A routed team counts when its
# Kafka message is produced, so a routed run caps messages and not finished rebuilds.
# With ~200k teams, 5000 is a starting point that processes all teams across ~40 runs.
# Run `python manage.py analyze_flags_cache_sizes` to measure actual memory usage.
# Based on typical flag data, 5000 teams ≈ 10-100 MB depending on flag complexity.
# See cache_expiry_manager.py for implementation details.
FLAGS_CACHE_REFRESH_LIMIT: int = get_from_env("FLAGS_CACHE_REFRESH_LIMIT", 5000, type_cast=int)

# Refresh sweep settings for the `flag_definitions` cache, which binds no `route_refresh_fn`
# and so always builds inline and always caps finished rebuilds. Each defaults to the
# `flags` value, which means raising the `flags` setting still raises this sweep until an
# operator pins these.
FLAG_DEFINITIONS_CACHE_REFRESH_TTL_THRESHOLD_HOURS: int = get_from_env(
    "FLAG_DEFINITIONS_CACHE_REFRESH_TTL_THRESHOLD_HOURS",
    FLAGS_CACHE_REFRESH_TTL_THRESHOLD_HOURS,
    type_cast=int,
)
FLAG_DEFINITIONS_CACHE_REFRESH_LIMIT: int = get_from_env(
    "FLAG_DEFINITIONS_CACHE_REFRESH_LIMIT", FLAGS_CACHE_REFRESH_LIMIT, type_cast=int
)

# Pacing for the teams the refresh sweep routes to the Kafka cache builder instead of
# building itself. The builder drains a batch sequentially, so a whole run produced at
# once sits in front of the flag edits raised after it and delays their rebuilds. The
# run pauses for CHUNK_DELAY_SECONDS after every CHUNK_SIZE routed teams. WINDOW_SECONDS
# caps the total pause, so a misconfigured chunk size or delay cannot make an hourly run
# outlive its schedule.
#
# The window has to stay under the worker pod's termination grace period, currently 1230
# seconds, because the pause happens inside the task and Celery waits for it on shutdown.
# A window at or above that means a deploy landing mid-sweep leaves the pod in Terminating
# for the rest of the run and then kills it before the end-of-run metrics push. 600 covers
# a fully routed run at the volumes the sweep sees today, which peak around 2,300 teams
# and need about 9 pauses. A larger run spends the window and routes the rest unpaced,
# which logs a warning.
# Per-deployment kill switch for routing the refresh sweep to the Kafka builder, read
# before the per-team flag. The flag cannot do this job: local evaluation resolves it
# against the single project key in posthog/apps.py, so raising it raises it in every
# region at once, including one whose flags-cache-builder still rejects the `source`
# field.
FLAGS_CACHE_REFRESH_KAFKA_ENABLED: bool = get_from_env(
    "FLAGS_CACHE_REFRESH_KAFKA_ENABLED", False, type_cast=str_to_bool
)

FLAGS_CACHE_REFRESH_KAFKA_CHUNK_SIZE: int = max(
    1, get_from_env("FLAGS_CACHE_REFRESH_KAFKA_CHUNK_SIZE", 250, type_cast=int)
)
FLAGS_CACHE_REFRESH_KAFKA_CHUNK_DELAY_SECONDS: float = max(
    0.0, get_from_env("FLAGS_CACHE_REFRESH_KAFKA_CHUNK_DELAY_SECONDS", 60.0, type_cast=float)
)
FLAGS_CACHE_REFRESH_KAFKA_WINDOW_SECONDS: float = max(
    0.0, get_from_env("FLAGS_CACHE_REFRESH_KAFKA_WINDOW_SECONDS", 600.0, type_cast=float)
)

# Batch size for flags cache verification. Each batch loads both cached data
# (from Redis) and DB data (FeatureFlag objects) into memory simultaneously.
# Teams with 100+ flags and large filters JSONs can use significant memory.
# Reduced from 1000 to 250 to prevent OOM. Decrease further if OOMs persist.
FLAGS_CACHE_VERIFICATION_CHUNK_SIZE: int = get_from_env("FLAGS_CACHE_VERIFICATION_CHUNK_SIZE", 250, type_cast=int)

# Grace period in minutes for skipping cache fixes during verification.
# If a flag was updated within this window, the verification task will skip
# "fixing" it to avoid race conditions with async cache update tasks.
# The next verification run will fix it if the cache is still stale.
FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES: int = get_from_env(
    "FLAGS_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES", 5, type_cast=int
)

# Batch size for team metadata cache verification. Team metadata is much smaller
# than flags data, so we can use larger batches without OOM risk.
TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE: int = get_from_env(
    "TEAM_METADATA_CACHE_VERIFICATION_CHUNK_SIZE", 1000, type_cast=int
)

# Grace period in minutes for skipping team metadata cache fixes during verification.
# If a team was updated within this window, the verification task will skip
# "fixing" it to avoid race conditions with async cache update tasks.
TEAM_METADATA_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES: int = get_from_env(
    "TEAM_METADATA_CACHE_VERIFICATION_GRACE_PERIOD_MINUTES", 5, type_cast=int
)

# Feature flag limits to prevent memory issues during flag evaluation/caching.
# These limits are configurable via environment variables and can be overridden
# in Helm charts per environment.
#
# Defaults are set well above observed production maximums to avoid impacting
# normal usage while protecting against extreme outliers.

# Maximum number of feature flags allowed per team. This is the fleet-wide default: staff can
# raise or lower it for a single team via TeamFeatureFlagsConfig.max_feature_flags_override.
# MAX_FEATURE_FLAG_FILTER_SIZE_BYTES below has no per-team override.
MAX_FEATURE_FLAGS_PER_TEAM: int = get_from_env("MAX_FEATURE_FLAGS_PER_TEAM", 2000, type_cast=int)

# Maximum size in bytes for a single flag's filters JSON
MAX_FEATURE_FLAG_FILTER_SIZE_BYTES: int = get_from_env(
    "MAX_FEATURE_FLAG_FILTER_SIZE_BYTES",
    512 * 1024,
    type_cast=int,  # 512KB
)

# Staged rollout for feature flag filters validation (#50084). Rule ids to reject on, comma
# separated, matching the ids in the violation metrics and in the `code` of each error this
# returns (e.g. "cross_field.variant_rollout_sum_not_100").
# "*" enforces every rule. Unset is the production default and rejects nothing new: both
# tiers still log and count violations, and the checks that predate #50084 still reject.
# Rules go in one at a time, each once its violation counter has stayed at zero — see the
# per-rule rollout in the issue. Defaults to "*" under TEST so the suite covers enforcement.
FEATURE_FLAG_FILTERS_ENFORCED_RULES: set[str] = get_set(
    get_from_env("FEATURE_FLAG_FILTERS_ENFORCED_RULES", "*" if TEST else "")
)

# Team ID for the local-evaluation canary. Unset disables the canary task.
FEATURE_FLAGS_CANARY_TEAM_ID: int | None = get_from_env("FEATURE_FLAGS_CANARY_TEAM_ID", optional=True, type_cast=int)

# Project secret API key (PSAK) scoped to team 2, used only by the EU cross-region
# dogfood flags sync (products/feature_flags/backend/cross_region_flag_sync.py) to
# poll team 2's flag definitions from the US region, since team 2 lives only in the
# US Postgres. Unset disables the sync. Not needed on US, where team 2's HyperCache
# entry is built locally via the normal signal-driven path.
POSTHOG_FLAGS_PROJECT_SECRET_TOKEN: str = get_from_env("POSTHOG_FLAGS_PROJECT_SECRET_TOKEN", "")
