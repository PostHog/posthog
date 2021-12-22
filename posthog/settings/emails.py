import os

from posthog.settings.utils import get_from_env, str_to_bool

# Email
EMAIL_ENABLED = get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool)
EMAIL_HOST = os.getenv("EMAIL_HOST", None)
EMAIL_PORT = os.getenv("EMAIL_PORT", "25")
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool)
EMAIL_USE_SSL = get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool)
DEFAULT_FROM_EMAIL = os.getenv("EMAIL_DEFAULT_FROM", os.getenv("DEFAULT_FROM_EMAIL", "root@localhost"))
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", None)

# TODO: Temporary
EMAIL_REPORTS_ENABLED: bool = get_from_env("EMAIL_REPORTS_ENABLED", False, type_cast=str_to_bool)
