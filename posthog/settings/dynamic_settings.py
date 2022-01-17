from posthog.settings.utils import get_from_env, str_to_bool

from .emails import (
    DEFAULT_FROM_EMAIL,
    EMAIL_ENABLED,
    EMAIL_HOST,
    EMAIL_HOST_PASSWORD,
    EMAIL_HOST_USER,
    EMAIL_PORT,
    EMAIL_REPLY_TO,
    EMAIL_USE_SSL,
    EMAIL_USE_TLS,
)

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
    "EMAIL_ENABLED": (EMAIL_ENABLED, "", bool,),
    "EMAIL_HOST": (EMAIL_HOST, "", str,),
    "EMAIL_PORT": (EMAIL_PORT, "", int,),
    "EMAIL_HOST_USER": (EMAIL_HOST_USER, "", str,),
    "EMAIL_HOST_PASSWORD": (EMAIL_HOST_PASSWORD, "", str,),
    "EMAIL_USE_TLS": (EMAIL_USE_TLS, "", bool,),
    "EMAIL_USE_SSL": (EMAIL_USE_SSL, "", bool,),
    "DEFAULT_FROM_EMAIL": (DEFAULT_FROM_EMAIL, "", str,),
    "EMAIL_REPLY_TO": (EMAIL_REPLY_TO, "", str,),
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
