import os

import structlog

from posthog.settings.utils import get_from_env, get_list, get_set
from posthog.utils import str_to_bool

logger = structlog.get_logger(__name__)

INGESTION_LAG_METRIC_TEAM_IDS = get_list(os.getenv("INGESTION_LAG_METRIC_TEAM_IDS", ""))

# KEEP IN SYNC WITH plugin-server/src/config/config.ts
BUFFER_CONVERSION_SECONDS = get_from_env("BUFFER_CONVERSION_SECONDS", default=60, type_cast=int)

# Whether or not random partitioning (i.e. overflow routing) should be allowed.
# (Enabling this setting does not cause messages to be randomly
# partitioned.) Note that this setting, if disabled, takes precedence over other
# partitioning-related settings below.
CAPTURE_ALLOW_RANDOM_PARTITIONING = get_from_env("CAPTURE_ALLOW_RANDOM_PARTITIONING", True, type_cast=str_to_bool)

# A list of <team_id:distinct_id> pairs (in the format 2:myLovelyId) that we should use
# random partitioning for when producing events to the Kafka topic consumed by the plugin server.
# This is a measure to handle hot partitions in ad-hoc cases.
EVENT_PARTITION_KEYS_TO_OVERRIDE = get_list(os.getenv("EVENT_PARTITION_KEYS_TO_OVERRIDE", ""))

# Keep in sync with plugin-server
EVENTS_DEAD_LETTER_QUEUE_STATSD_METRIC = "events_added_to_dead_letter_queue"

QUOTA_LIMITING_ENABLED = get_from_env("QUOTA_LIMITING_ENABLED", False, type_cast=str_to_bool)
# when enabled we will return content in capture responses if recordings are quota limited
# session recording clients can stop sending events if they receive a quota limited response
RECORDINGS_QUOTA_LIMITING_RESPONSES_SAMPLE_RATE = get_from_env(
    "RECORDINGS_QUOTA_LIMITING_RESPONSES_SAMPLE_RATE", default=0, type_cast=float
)

# Capture-side overflow detection for analytics events.
# Not accurate enough, superseded by detection in plugin-server and should be phased out.
PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED = get_from_env(
    "PARTITION_KEY_AUTOMATIC_OVERRIDE_ENABLED", type_cast=bool, default=False
)
PARTITION_KEY_BUCKET_CAPACITY = get_from_env("PARTITION_KEY_BUCKET_CAPACITY", type_cast=int, default=1000)
PARTITION_KEY_BUCKET_REPLENTISH_RATE = get_from_env(
    "PARTITION_KEY_BUCKET_REPLENTISH_RATE", type_cast=float, default=1.0
)

# Overflow configuration for session replay
REPLAY_OVERFLOW_FORCED_TOKENS = get_set(os.getenv("REPLAY_OVERFLOW_FORCED_TOKENS", ""))
REPLAY_OVERFLOW_SESSIONS_ENABLED = get_from_env("REPLAY_OVERFLOW_SESSIONS_ENABLED", type_cast=bool, default=False)

REPLAY_RETENTION_DAYS_MIN = get_from_env("REPLAY_RETENTION_DAYS_MIN", type_cast=int, default=30)
REPLAY_RETENTION_DAYS_MAX = get_from_env("REPLAY_RETENTION_DAYS_MAX", type_cast=int, default=90)
REPLAY_CAPTURE_ENDPOINT = os.getenv("REPLAY_CAPTURE_ENDPOINT", "/s/")

CAPTURE_INTERNAL_URL = os.getenv("CAPTURE_INTERNAL_URL", "http://localhost:8010")
CAPTURE_REPLAY_INTERNAL_URL = os.getenv("CAPTURE_REPLAY_INTERNAL_URL", "http://localhost:8010")

# Internal OTLP/HTTP endpoint for first-party log emission into Logs (the `capture-logs` service,
# path `/i/v1/logs`). The OTLP Bearer (a project token) routes records to a team's Logs. Defaults to
# empty = emission disabled (the activity skips/raises rather than shipping to the wrong place); set
# per-region via charts in prod, and to the local capture proxy when testing locally.
OTLP_LOGS_INGEST_ENDPOINT = os.getenv("OTLP_LOGS_INGEST_ENDPOINT", "")
# Thread-pool size for capture_internal batch chunk fan-out (default 8, was per-event fan-out pre-v1).
CAPTURE_INTERNAL_MAX_WORKERS = get_from_env("CAPTURE_INTERNAL_MAX_WORKERS", type_cast=int, default=8)

NEW_ANALYTICS_CAPTURE_ENDPOINT = os.getenv("NEW_CAPTURE_ENDPOINT", "/i/v0/e/")

CAPTURE_V1_INTERNAL_ENDPOINT = os.getenv("CAPTURE_V1_INTERNAL_ENDPOINT", "/i/v1/analytics/events")
CAPTURE_V1_INTERNAL_MAX_ATTEMPTS = get_from_env("CAPTURE_V1_INTERNAL_MAX_ATTEMPTS", type_cast=int, default=4)
CAPTURE_V1_INTERNAL_RETRY_AFTER_CAP_SECONDS = get_from_env(
    "CAPTURE_V1_INTERNAL_RETRY_AFTER_CAP_SECONDS", type_cast=float, default=5.0
)
# Chunk fan-out reuses CAPTURE_INTERNAL_MAX_WORKERS (above) for its thread pool.
CAPTURE_INTERNAL_BATCH_CHUNK_SIZE = get_from_env("CAPTURE_INTERNAL_BATCH_CHUNK_SIZE", type_cast=int, default=200)

# Buffered CSP capture-forward: when enabled, /report/ enqueues accepted reports to a
# bounded in-process buffer and returns 204 immediately; a background thread batches
# them to capture-rs. Keeps request-worker hold time independent of capture-rs latency,
# which is required for servers with bounded worker pools (WSGI). Off = legacy
# synchronous forward.
CSP_REPORT_BUFFERED_FORWARD = get_from_env("CSP_REPORT_BUFFERED_FORWARD", False, type_cast=str_to_bool)
CSP_REPORT_BUFFER_MAX_EVENTS = get_from_env("CSP_REPORT_BUFFER_MAX_EVENTS", type_cast=int, default=10000)
CSP_REPORT_BUFFER_FLUSH_INTERVAL_SECONDS = get_from_env(
    "CSP_REPORT_BUFFER_FLUSH_INTERVAL_SECONDS", type_cast=float, default=0.5
)
CSP_REPORT_BUFFER_FLUSH_MAX_EVENTS = get_from_env("CSP_REPORT_BUFFER_FLUSH_MAX_EVENTS", type_cast=int, default=1000)
# Wall-clock ceiling per flush: token groups are submitted serially, so many
# distinct tokens against a slow capture-rs would otherwise stall the sender for
# the sum of every group's transport budget. Events still unsent at the deadline
# are dropped (reason="flush_deadline"). A healthy flush finishes well under a
# second; the ceiling only bites while capture-rs degrades.
CSP_REPORT_BUFFER_FLUSH_MAX_SECONDS = get_from_env("CSP_REPORT_BUFFER_FLUSH_MAX_SECONDS", type_cast=float, default=5.0)
# Fairness: the largest share of the buffer any single token may hold, so one
# token's report storm cannot evict every other token's events on overflow.
CSP_REPORT_BUFFER_MAX_TOKEN_SHARE = get_from_env("CSP_REPORT_BUFFER_MAX_TOKEN_SHARE", type_cast=float, default=0.5)
# Memory bounds: the count cap alone doesn't bound memory because events carry the
# raw report body. Per-event cap rejects pathological payloads (legit CSP reports
# are a few KB); the total cap evicts oldest when crossed.
CSP_REPORT_BUFFER_MAX_EVENT_BYTES = get_from_env("CSP_REPORT_BUFFER_MAX_EVENT_BYTES", type_cast=int, default=64 * 1024)
CSP_REPORT_BUFFER_MAX_BYTES = get_from_env("CSP_REPORT_BUFFER_MAX_BYTES", type_cast=int, default=64 * 1024 * 1024)
NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS = get_set(os.getenv("NEW_ANALYTICS_CAPTURE_EXCLUDED_TEAM_IDS", ""))

ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS = get_set(os.getenv("ELEMENT_CHAIN_AS_STRING_EXCLUDED_TEAMS", ""))

DROP_EVENTS_BY_TOKEN_DISTINCT_ID = get_from_env("DROP_EVENTS_BY_TOKEN_DISTINCT_ID", None, type_cast=str, optional=True)
