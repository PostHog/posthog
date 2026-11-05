from posthog.settings.utils import get_from_env, str_to_bool

PERSONHOG_ADDR = get_from_env("PERSONHOG_ADDR", "")
PERSONHOG_TIMEOUT_MS = get_from_env("PERSONHOG_TIMEOUT_MS", 5000, type_cast=int)

# A router with the identity proxy enabled; empty means the lifecycle path is unavailable here.
PERSONHOG_LIFECYCLE_ADDR = get_from_env("PERSONHOG_LIFECYCLE_ADDR", "")
# Above the identity server's own execute timeout (30 s by default), after which it answers
# UNAVAILABLE itself; a shorter client deadline would abandon calls the server was about to answer.
PERSONHOG_LIFECYCLE_TIMEOUT_MS = get_from_env("PERSONHOG_LIFECYCLE_TIMEOUT_MS", 45_000, type_cast=int)

# Deadline per saga call on the request path (the person API), which holds a web worker while the saga
# runs and retries. Background callers keep PERSONHOG_LIFECYCLE_TIMEOUT_MS. Keep it above the identity
# server's lifecycle_execute_timeout_secs (30 s): a shorter deadline makes the API report a failure for a
# slow saga that still commits the delete, so the person is gone with no response or activity log for it.
PERSON_DELETE_LIFECYCLE_REQUEST_TIMEOUT_MS = get_from_env(
    "PERSON_DELETE_LIFECYCLE_REQUEST_TIMEOUT_MS", 35_000, type_cast=int
)

# gRPC channel options
PERSONHOG_KEEPALIVE_TIME_MS = get_from_env("PERSONHOG_KEEPALIVE_TIME_MS", 30_000, type_cast=int)
PERSONHOG_KEEPALIVE_TIMEOUT_MS = get_from_env("PERSONHOG_KEEPALIVE_TIMEOUT_MS", 5_000, type_cast=int)
PERSONHOG_KEEPALIVE_WITHOUT_CALLS = get_from_env("PERSONHOG_KEEPALIVE_WITHOUT_CALLS", True, type_cast=str_to_bool)
PERSONHOG_MAX_RECONNECT_BACKOFF_MS = get_from_env("PERSONHOG_MAX_RECONNECT_BACKOFF_MS", 5_000, type_cast=int)
PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS = get_from_env("PERSONHOG_INITIAL_RECONNECT_BACKOFF_MS", 1_000, type_cast=int)
PERSONHOG_MAX_SEND_MESSAGE_LENGTH = get_from_env("PERSONHOG_MAX_SEND_MESSAGE_LENGTH", 4 * 1024 * 1024, type_cast=int)
PERSONHOG_MAX_RECV_MESSAGE_LENGTH = get_from_env("PERSONHOG_MAX_RECV_MESSAGE_LENGTH", 128 * 1024 * 1024, type_cast=int)
PERSONHOG_CLIENT_IDLE_TIMEOUT_MS = get_from_env("PERSONHOG_CLIENT_IDLE_TIMEOUT_MS", 0, type_cast=int)

# Where person writes go: "replica" writes Postgres directly, "leader" goes through the personhog leader.
PERSONHOG_WRITE_PATH = get_from_env("PERSONHOG_WRITE_PATH", "replica")
if PERSONHOG_WRITE_PATH not in ("replica", "leader"):
    raise ValueError(f"PERSONHOG_WRITE_PATH must be 'replica' or 'leader', got {PERSONHOG_WRITE_PATH!r}")

# Retry settings for transient gRPC errors
PERSONHOG_MAX_RETRIES = get_from_env("PERSONHOG_MAX_RETRIES", 2, type_cast=int)
PERSONHOG_INITIAL_BACKOFF_MS = get_from_env("PERSONHOG_INITIAL_BACKOFF_MS", 50, type_cast=int)
PERSONHOG_MAX_BACKOFF_MS = get_from_env("PERSONHOG_MAX_BACKOFF_MS", 1000, type_cast=int)

# Server enforces a hard limit of 250 IDs per batch lookup request for person records.
_PERSONHOG_MAX_BATCH_SIZE = 250
PERSONHOG_BATCH_SIZE: int = max(
    1, min(get_from_env("PERSONHOG_BATCH_SIZE", _PERSONHOG_MAX_BATCH_SIZE, type_cast=int), _PERSONHOG_MAX_BATCH_SIZE)
)
