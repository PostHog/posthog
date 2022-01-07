from posthog.settings.utils import get_from_env, str_to_bool

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_DATABASE_PREFIX = "constance:posthog:"

CONSTANCE_CONFIG = {
    "MATERIALIZED_COLUMNS_ENABLED": (
        get_from_env("MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool),
        "Whether materialized columns should be created or used at query time",
        bool,
    ),
    "COMPUTE_MATERIALIZED_COLUMNS_ENABLED": (
        get_from_env("COMPUTE_MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool),
        "Whether materialized columns should be created or updated (existing columns will still be used at query time)",
        bool,
    ),
    "AUTO_START_ASYNC_MIGRATIONS": (
        get_from_env("AUTO_START_ASYNC_MIGRATIONS", False, type_cast=str_to_bool),
        "Whether the earliest unapplied async migration should be triggered automatically on server startup",
        bool,
    ),
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT": (
        get_from_env("ASYNC_MIGRATION_ROLLBACK_TIMEOUT", 30, type_cast=int),
        "The timeout for completing the full rollback of an async migration",
        bool,
    ),
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK": (
        get_from_env("ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", False, type_cast=str_to_bool),
        "Used to disable automatic rollback of failed async migrations",
        bool,
    ),
}
