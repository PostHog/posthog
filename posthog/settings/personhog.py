from posthog.settings.utils import get_from_env, str_to_bool

PERSONHOG_ADDR = get_from_env("PERSONHOG_ADDR", "")
PERSONHOG_TIMEOUT_MS = get_from_env("PERSONHOG_TIMEOUT_MS", 5000, type_cast=int)

# gRPC channel options
PERSONHOG_KEEPALIVE_TIME_MS = get_from_env("PERSONHOG_KEEPALIVE_TIME_MS", 30_000, type_cast=int)
PERSONHOG_KEEPALIVE_TIMEOUT_MS = get_from_env("PERSONHOG_KEEPALIVE_TIMEOUT_MS", 5_000, type_cast=int)
PERSONHOG_KEEPALIVE_WITHOUT_CALLS = get_from_env("PERSONHOG_KEEPALIVE_WITHOUT_CALLS", True, type_cast=str_to_bool)
PERSONHOG_MAX_RECONNECT_BACKOFF_MS = get_from_env("PERSONHOG_MAX_RECONNECT_BACKOFF_MS", 5_000, type_cast=int)
PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS = get_from_env("PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS", 1_000, type_cast=int)
PERSONHOG_MAX_SEND_MESSAGE_LENGTH = get_from_env("PERSONHOG_MAX_SEND_MESSAGE_LENGTH", 4 * 1024 * 1024, type_cast=int)
PERSONHOG_MAX_RECV_MESSAGE_LENGTH = get_from_env("PERSONHOG_MAX_RECV_MESSAGE_LENGTH", 128 * 1024 * 1024, type_cast=int)
PERSONHOG_CLIENT_IDLE_TIMEOUT_MS = get_from_env("PERSONHOG_CLIENT_IDLE_TIMEOUT_MS", 0, type_cast=int)

# Retry settings for transient gRPC errors
PERSONHOG_MAX_RETRIES = get_from_env("PERSONHOG_MAX_RETRIES", 2, type_cast=int)
PERSONHOG_INITIAL_BACKOFF_MS = get_from_env("PERSONHOG_INITIAL_BACKOFF_MS", 50, type_cast=int)
PERSONHOG_MAX_BACKOFF_MS = get_from_env("PERSONHOG_MAX_BACKOFF_MS", 1000, type_cast=int)

# Server enforces a hard limit of 250 IDs per batch lookup request for person records.
_PERSONHOG_MAX_BATCH_SIZE = 250
PERSONHOG_BATCH_SIZE: int = max(
    1, min(get_from_env("PERSONHOG_BATCH_SIZE", _PERSONHOG_MAX_BATCH_SIZE, type_cast=int), _PERSONHOG_MAX_BATCH_SIZE)
)

# Concurrent in-flight batch lookups for callers that opt into the batched-read fan-out
# (currently only the experiment freeze-exposure resolve; batched reads are sequential by
# default). The shared HTTP/2 channel multiplexes streams, so this opens no extra connections —
# but each in-flight RPC can occupy up to bulk_max_concurrent_chunks of a replica's small bulk
# Postgres pool, so keep this modest. 1 disables the fan-out (fully sequential).
PERSONHOG_BATCH_CONCURRENCY: int = max(1, get_from_env("PERSONHOG_BATCH_CONCURRENCY", 4, type_cast=int))
