from posthog.settings.utils import get_from_env, str_to_bool

# To help reduce PG load during deploys we're setting this to True by default.
# We don't currently have any async migrations that need to be added/ran.
SKIP_ASYNC_MIGRATIONS_SETUP = get_from_env("SKIP_ASYNC_MIGRATIONS_SETUP", True, type_cast=str_to_bool)

ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS = get_from_env(
    "ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS", 2 * 60 * 60, type_cast=int
)

# Boot-time resilience for setup_async_migrations() when Postgres is briefly unreachable
# (DNS not yet resolving, or the DB replaying WAL in recovery mode after a restart/failover).
# We retry with exponential backoff and, if still unreachable, log and continue so the worker
# boots instead of crash-looping.
ASYNC_MIGRATIONS_SETUP_MAX_ATTEMPTS = get_from_env("ASYNC_MIGRATIONS_SETUP_MAX_ATTEMPTS", 5, type_cast=int)
ASYNC_MIGRATIONS_SETUP_RETRY_BASE_DELAY_SECONDS = get_from_env(
    "ASYNC_MIGRATIONS_SETUP_RETRY_BASE_DELAY_SECONDS", 1.0, type_cast=float
)
