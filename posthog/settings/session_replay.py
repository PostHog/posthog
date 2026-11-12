from posthog.settings import get_from_env
from posthog.utils import str_to_bool

# TRICKY: we saw unusual memory usage behavior in EU clickhouse cluster
# when allowing use of denormalized properties in some session replay event queries
# it is likely this can be returned to the default of True in future but would need careful monitoring
ALLOW_DENORMALIZED_PROPS_IN_LISTING = get_from_env("ALLOW_DENORMALIZED_PROPS_IN_LISTING", False, type_cast=str_to_bool)

REPLAY_MESSAGE_TOO_LARGE_SAMPLE_RATE = get_from_env("REPLAY_MESSAGE_TOO_LARGE_SAMPLE_RATE", 0, type_cast=float)
REPLAY_MESSAGE_TOO_LARGE_SAMPLE_BUCKET = get_from_env(
    "REPLAY_MESSAGE_TOO_LARGE_SAMPLE_BUCKET", "posthog-cloud-prod-us-east-1-k8s-replay-samples"
)

# an AI model to use for session recording filters
SESSION_REPLAY_AI_REGEX_MODEL = get_from_env("SESSION_REPLAY_AI_REGEX_MODEL", "gpt-6-luna")

PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS = get_from_env(
    "PLAYLIST_COUNTER_PROCESSING_COOLDOWN_SECONDS", 3600, type_cast=int
)

PLAYLIST_COUNTER_PROCESSING_PLAYLISTS_LIMIT = get_from_env(
    "PLAYLIST_COUNTER_PROCESSING_PLAYLISTS_LIMIT", 2500, type_cast=int
)


SNAPSHOT_RATE_FREE_BURST = get_from_env("SNAPSHOT_RATE_FREE_BURST", "12/minute")
SNAPSHOT_RATE_FREE_SUSTAINED = get_from_env("SNAPSHOT_RATE_FREE_SUSTAINED", "60/hour")
SNAPSHOT_RATE_PAID_BURST = get_from_env("SNAPSHOT_RATE_PAID_BURST", "60/minute")
SNAPSHOT_RATE_PAID_SUSTAINED = get_from_env("SNAPSHOT_RATE_PAID_SUSTAINED", "300/hour")
SNAPSHOT_RATE_ENTERPRISE_BURST = get_from_env("SNAPSHOT_RATE_ENTERPRISE_BURST", "100/minute")
SNAPSHOT_RATE_ENTERPRISE_SUSTAINED = get_from_env("SNAPSHOT_RATE_ENTERPRISE_SUSTAINED", "400/hour")

LISTING_RATE_FREE_BURST = get_from_env("LISTING_RATE_FREE_BURST", "12/minute")
LISTING_RATE_FREE_SUSTAINED = get_from_env("LISTING_RATE_FREE_SUSTAINED", "60/hour")
LISTING_RATE_PAID_BURST = get_from_env("LISTING_RATE_PAID_BURST", "60/minute")
LISTING_RATE_PAID_SUSTAINED = get_from_env("LISTING_RATE_PAID_SUSTAINED", "300/hour")
LISTING_RATE_ENTERPRISE_BURST = get_from_env("LISTING_RATE_ENTERPRISE_BURST", "100/minute")
LISTING_RATE_ENTERPRISE_SUSTAINED = get_from_env("LISTING_RATE_ENTERPRISE_SUSTAINED", "400/hour")

# Cap on whole-recording raw snapshot streams. One stream reads every block of a recording, so these rates are far
# below the per-request snapshot rates above. Each personal API key has its own bucket, and so does each user who
# calls without one.
RAW_SNAPSHOT_STREAM_RATE_FREE_BURST = get_from_env("RAW_SNAPSHOT_STREAM_RATE_FREE_BURST", "2/minute")
RAW_SNAPSHOT_STREAM_RATE_FREE_SUSTAINED = get_from_env("RAW_SNAPSHOT_STREAM_RATE_FREE_SUSTAINED", "20/hour")
RAW_SNAPSHOT_STREAM_RATE_PAID_BURST = get_from_env("RAW_SNAPSHOT_STREAM_RATE_PAID_BURST", "10/minute")
RAW_SNAPSHOT_STREAM_RATE_PAID_SUSTAINED = get_from_env("RAW_SNAPSHOT_STREAM_RATE_PAID_SUSTAINED", "100/hour")
RAW_SNAPSHOT_STREAM_RATE_ENTERPRISE_BURST = get_from_env("RAW_SNAPSHOT_STREAM_RATE_ENTERPRISE_BURST", "20/minute")
RAW_SNAPSHOT_STREAM_RATE_ENTERPRISE_SUSTAINED = get_from_env(
    "RAW_SNAPSHOT_STREAM_RATE_ENTERPRISE_SUSTAINED", "200/hour"
)

# Per-user cap on blob fetches from a browser session or an OAuth token. The tier rates above cover only personal
# API keys, so without this a script, browser agent or MCP client can fetch snapshots with no limit at all.
SNAPSHOT_USER_RATE_BURST = get_from_env("SNAPSHOT_USER_RATE_BURST", "200/minute")
SNAPSHOT_USER_RATE_SUSTAINED = get_from_env("SNAPSHOT_USER_RATE_SUSTAINED", "3000/hour")
# Off means log-only: an over-limit fetch is counted in session_recording_api_throttled_total but still served.
SNAPSHOT_USER_RATE_LIMIT_ENFORCED = get_from_env("SNAPSHOT_USER_RATE_LIMIT_ENFORCED", False, type_cast=str_to_bool)

# Per-token cap for replay endpoints reached via a SharingAccessToken.
REPLAY_SHARING_TOKEN_RATE = get_from_env("REPLAY_SHARING_TOKEN_RATE", "600/minute")
