from posthog.settings.utils import get_from_env, str_to_bool

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

CONSTANCE_DATABASE_PREFIX = "constance:posthog:"

CONSTANCE_CONFIG = {
    "MATERIALIZED_COLUMNS_ENABLED": (
        get_from_env("MATERIALIZED_COLUMNS_ENABLED", True, type_cast=str_to_bool),
        "Whether materialized columns should be, created or used at query time",
        bool,
    ),
}
