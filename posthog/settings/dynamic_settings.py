from posthog.settings.utils import get_from_env, str_to_bool

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_DATABASE_PREFIX = "constance:posthog:"

# Warning: Dynamically updating these settings should only be done through the API.
CONSTANCE_CONFIG = {
    "RECORDINGS_TTL_WEEKS": (
        3,
        "Number of weeks recordings will be kept before removing them (for all projects). Storing recordings for a shorter timeframe can help reduce Clickhouse disk usage.",
        int,
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
    "ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS": (
        get_from_env("ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS", 60 * 30, type_cast=int),
        "Sets the default timeout for completing an async migration operation.",
        int,
    ),
    "ASYNC_MIGRATIONS_AUTO_CONTINUE": (
        get_from_env("ASYNC_MIGRATIONS_AUTO_CONTINUE", True, type_cast=str_to_bool),
        "Whether to resume the migration, when celery worker crashed.",
        bool,
    ),
    "EMAIL_ENABLED": (
        get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool),
        "Whether email service is enabled or not.",
        bool,
    ),
    "EMAIL_HOST": (
        get_from_env("EMAIL_HOST", optional=True),
        "Hostname to connect to for establishing SMTP connections.",
        str,
    ),
    "EMAIL_PORT": (
        get_from_env("EMAIL_PORT", 25, type_cast=int),
        "Port that should be used to connect to the email host.",
        int,
    ),
    "EMAIL_HOST_USER": (
        get_from_env("EMAIL_HOST_USER", optional=True),
        "Credentials to connect to the email host.",
        str,
    ),
    "EMAIL_HOST_PASSWORD": (
        get_from_env("EMAIL_HOST_PASSWORD", optional=True),
        "Credentials to connect to the email host.",
        str,
    ),
    "EMAIL_USE_TLS": (
        get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool),
        "Whether to use TLS protocol when connecting to the email host.",
        bool,
    ),
    "EMAIL_USE_SSL": (
        get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool),
        "Whether to use SSL protocol when connecting to the email host.",
        bool,
    ),
    "EMAIL_DEFAULT_FROM": (
        get_from_env("EMAIL_DEFAULT_FROM", get_from_env("DEFAULT_FROM_EMAIL", "root@localhost")),
        "Email address that will appear as the sender in emails (From header).",
        str,
    ),
    "EMAIL_REPLY_TO": (
        get_from_env("EMAIL_REPLY_TO", ""),
        "Reply address to which email clients should send responses.",
        str,
    ),
    "ASYNC_MIGRATIONS_OPT_OUT_EMAILS": (
        get_from_env("ASYNC_MIGRATIONS_OPT_OUT_EMAILS", False, type_cast=str_to_bool),
        "Used to disable emails from async migrations service",
        bool,
    ),
}

SETTINGS_ALLOWING_API_OVERRIDE = (
    "RECORDINGS_TTL_WEEKS",
    "AUTO_START_ASYNC_MIGRATIONS",
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK",
    "ASYNC_MIGRATIONS_DEFAULT_TIMEOUT_SECONDS",
    "ASYNC_MIGRATIONS_AUTO_CONTINUE",
    "EMAIL_ENABLED",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "EMAIL_DEFAULT_FROM",
    "EMAIL_REPLY_TO",
    "ASYNC_MIGRATIONS_OPT_OUT_EMAILS",
)
