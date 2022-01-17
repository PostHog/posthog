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
        int,
    ),
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK": (
        get_from_env("ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK", False, type_cast=str_to_bool),
        "Used to disable automatic rollback of failed async migrations",
        bool,
    ),
    "EMAIL_ENABLED": (get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool), "", bool,),
    "EMAIL_HOST": (get_from_env("EMAIL_HOST"), "", str,),
    "EMAIL_PORT": (get_from_env("EMAIL_PORT", 25, type_cast=int), "", int,),
    "EMAIL_HOST_USER": (get_from_env("EMAIL_HOST_USER"), "", str,),
    "EMAIL_HOST_PASSWORD": (get_from_env("EMAIL_HOST_PASSWORD"), "", str,),
    "EMAIL_USE_TLS": (get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool), "", bool,),
    "EMAIL_USE_SSL": (get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool), "", bool,),
    "DEFAULT_FROM_EMAIL": (
        get_from_env("EMAIL_DEFAULT_FROM", get_from_env("DEFAULT_FROM_EMAIL", "root@localhost")),
        "",
        str,
    ),
    "EMAIL_REPLY_TO": (get_from_env("EMAIL_REPLY_TO"), "", str,),
}

SETTINGS_ALLOWING_API_OVERRIDE = (
    "AUTO_START_ASYNC_MIGRATIONS",
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK",
    "EMAIL_ENABLED",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_REPLY_TO",
)
