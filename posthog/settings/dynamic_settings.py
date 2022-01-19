from posthog.settings.utils import get_from_env, str_to_bool

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_DATABASE_PREFIX = "constance:posthog:"

# Warning: Dynamically updating these settings should only be done through the API.
CONSTANCE_CONFIG = {
    "RECORDINGS_TTL_WEEKS": (
        get_from_env("RECORDINGS_TTL_WEEKS", 3, type_cast=int),
        "Number of weeks recordings will be kept before removing them (for all projects). Storing recordings for a shorter timeframe can help reduce Clickhouse disk usage.",
        bool,
    ),
    "MATERIALIZED_COLUMNS_ENABLED": (
        get_from_env("MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool),
        "Whether materialized columns should be created or used at query time.",
        bool,
    ),
    "COMPUTE_MATERIALIZED_COLUMNS_ENABLED": (
        get_from_env("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool),
        "Whether materialized columns should be created or updated (existing columns will still be used at query time).",
        bool,
    ),
    "AUTO_START_ASYNC_MIGRATIONS": (
        get_from_env("AUTO_START_ASYNC_MIGRATIONS", False, type_cast=str_to_bool),
        "Whether the earliest unapplied async migration should be triggered automatically on server startup.",
        bool,
    ),
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT": (
        get_from_env("ASYNC_MIGRATION_ROLLBACK_TIMEOUT", 30, type_cast=int),
        "The timeout for completing the full rollback of an async migration.",
        int,
    ),
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK": (
        get_from_env("ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", False, type_cast=str_to_bool),
        "Used to disable automatic rollback of failed async migrations.",
        bool,
    ),
}

SETTINGS_ALLOWING_API_OVERRIDE = (
    "RECORDINGS_TTL_WEEKS",
    "AUTO_START_ASYNC_MIGRATIONS",
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK",
)
