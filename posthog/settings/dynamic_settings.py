from posthog.settings.utils import get_from_env, str_to_bool

CONSTANCE_DATABASE_PREFIX = "constance:posthog:"

# Warning: Dynamically updating these settings should only be done through the API.
# CONSTANCE_CONFIG: https://django-constance.readthedocs.io/en/latest/
#
# To edit, visit: ${SITE_URL}/admin/posthog/instancesetting/

CONSTANCE_CONFIG = {
    "RECORDINGS_TTL_WEEKS": (
        3,
        "Number of weeks recordings will be kept before removing them (for all projects). Storing recordings for a shorter timeframe can help reduce Clickhouse disk usage.",
        int,
    ),
    "RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS": (
        3,
        "Number of weeks recording performance events will be kept before removing them (for all projects). Storing performance events for a shorter timeframe can help reduce Clickhouse disk usage.",
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
    "AGGREGATE_BY_DISTINCT_IDS_TEAMS": (
        get_from_env("AGGREGATE_BY_DISTINCT_IDS_TEAMS", ""),
        "Whether unique users should be counted by distinct IDs. Speeds up queries at the cost of accuracy.",
        str,
    ),
    "PERSON_ON_EVENTS_ENABLED": (
        get_from_env("PERSON_ON_EVENTS_ENABLED", False, type_cast=str_to_bool),
        "Whether to use query path using person_id and person_properties on events or the old query",
        bool,
    ),
    "PERSON_ON_EVENTS_V2_ENABLED": (
        get_from_env("PERSON_ON_EVENTS_V2_ENABLED", False, type_cast=str_to_bool),
        "Whether to use query path using person_id and person_properties on events or the old query",
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
    "ASYNC_MIGRATIONS_AUTO_CONTINUE": (
        get_from_env("ASYNC_MIGRATIONS_AUTO_CONTINUE", True, type_cast=str_to_bool),
        "Whether to resume the migration, when celery worker crashed.",
        bool,
    ),
    "ASYNC_MIGRATIONS_BLOCK_UPGRADE": (
        get_from_env("ASYNC_MIGRATIONS_BLOCK_UPGRADE", True, type_cast=str_to_bool),
        "(Advanced) Whether having an async migration running, errored or required should prevent upgrades.",
        bool,
    ),
    "ASYNC_MIGRATIONS_IGNORE_POSTHOG_VERSION": (
        get_from_env("ASYNC_MIGRATIONS_IGNORE_POSTHOG_VERSION", False, type_cast=str_to_bool),
        "(Advanced) Whether to ignore async migrations posthog version restrictions",
        bool,
    ),
    "STRICT_CACHING_TEAMS": (
        get_from_env("STRICT_CACHING_TEAMS", ""),
        "Whether to always try to find cached data for historical intervals on trends",
        str,
    ),
    "EMAIL_ENABLED": (
        get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool),
        "Whether email service is enabled or not.",
        bool,
    ),
    "EMAIL_HOST": (
        get_from_env("EMAIL_HOST", default=""),
        "Hostname to connect to for establishing SMTP connections.",
        str,
    ),
    "EMAIL_PORT": (
        get_from_env("EMAIL_PORT", 25, type_cast=int),
        "Port that should be used to connect to the email host.",
        int,
    ),
    "EMAIL_HOST_USER": (
        get_from_env(
            "EMAIL_HOST_USER", default=""
        ),  # we use default='' so an unconfigured value is an empty string, not a `None`
        "Credentials to connect to the email host.",
        str,
    ),
    "EMAIL_HOST_PASSWORD": (
        get_from_env("EMAIL_HOST_PASSWORD", default=""),
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
        get_from_env("EMAIL_REPLY_TO", default=""),
        "Reply address to which email clients should send responses.",
        str,
    ),
    "ASYNC_MIGRATIONS_OPT_OUT_EMAILS": (
        get_from_env("ASYNC_MIGRATIONS_OPT_OUT_EMAILS", False, type_cast=str_to_bool),
        "Used to disable emails from async migrations service",
        bool,
    ),
    "GITHUB_APP_SLUG": (
        get_from_env("GITHUB_APP_SLUG", default=""),
        "Used to redirect to the correct GitHub App installation page",
        str,
    ),
    "SLACK_APP_CLIENT_ID": (
        get_from_env("SLACK_APP_CLIENT_ID", default=""),
        "Used to enable the 'Add to Slack' button across all projects",
        str,
    ),
    "SLACK_APP_CLIENT_SECRET": (
        get_from_env("SLACK_APP_CLIENT_SECRET", default=""),
        "Used to enable the 'Add to Slack' button across all projects",
        str,
    ),
    "SLACK_APP_SIGNING_SECRET": (
        get_from_env("SLACK_APP_SIGNING_SECRET", default=""),
        "Used to validate Slack events for example when unfurling links",
        str,
    ),
    "PARALLEL_DASHBOARD_ITEM_CACHE": (
        get_from_env("PARALLEL_DASHBOARD_ITEM_CACHE", default=5),
        "user to determine how many insight cache updates to run at a time",
        int,
    ),
    "ALLOW_EXPERIMENTAL_ASYNC_MIGRATIONS": (
        get_from_env("ALLOW_EXPERIMENTAL_ASYNC_MIGRATIONS", default=False),
        "Used to enable the running of experimental async migrations",
        bool,
    ),
    "RATE_LIMIT_ENABLED": (
        get_from_env("RATE_LIMIT_ENABLED", False, type_cast=str_to_bool),
        "Whether rate limiting is enabled",
        bool,
    ),
    "RATE_LIMITING_ALLOW_LIST_TEAMS": (
        get_from_env("RATE_LIMITING_ALLOW_LIST_TEAMS", ""),
        "Whether teams are on an allow list to bypass rate limiting. Comma separated list of team-ids",
        str,
    ),
    "REDIRECT_APP_TO_US": (
        get_from_env("REDIRECT_APP_TO_US", False, type_cast=str_to_bool),
        "Temporary option to redirect all app traffic from app.posthog.com to us.posthog.com.",
        bool,
    ),
}

SETTINGS_ALLOWING_API_OVERRIDE = (
    "RECORDINGS_TTL_WEEKS",
    "RECORDINGS_PERFORMANCE_EVENTS_TTL_WEEKS",
    "AUTO_START_ASYNC_MIGRATIONS",
    "AGGREGATE_BY_DISTINCT_IDS_TEAMS",
    "ASYNC_MIGRATIONS_ROLLBACK_TIMEOUT",
    "ASYNC_MIGRATIONS_DISABLE_AUTO_ROLLBACK",
    "ASYNC_MIGRATIONS_AUTO_CONTINUE",
    "ASYNC_MIGRATIONS_BLOCK_UPGRADE",
    "ASYNC_MIGRATIONS_IGNORE_POSTHOG_VERSION",
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
    "PERSON_ON_EVENTS_ENABLED",
    "PERSON_ON_EVENTS_V2_ENABLED",
    "STRICT_CACHING_TEAMS",
    "GITHUB_APP_SLUG",
    "SLACK_APP_CLIENT_ID",
    "SLACK_APP_CLIENT_SECRET",
    "SLACK_APP_SIGNING_SECRET",
    "PARALLEL_DASHBOARD_ITEM_CACHE",
    "ALLOW_EXPERIMENTAL_ASYNC_MIGRATIONS",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMITING_ALLOW_LIST_TEAMS",
    "REDIRECT_APP_TO_US",
)

# SECRET_SETTINGS can only be updated but will never be exposed through the API (we do store them plain text in the DB)
# On the frontend UI will clearly show which configuration elements are secret and whether they have a set value or not.
SECRET_SETTINGS = [
    "EMAIL_HOST_PASSWORD",
    "SLACK_APP_CLIENT_SECRET",
    "SLACK_APP_SIGNING_SECRET",
]
