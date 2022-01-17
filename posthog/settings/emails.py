from constance.signals import config_updated
from django.dispatch.dispatcher import receiver

from posthog.settings.utils import get_from_env, str_to_bool

EMAIL_SETTINGS = [
    "EMAIL_ENABLED",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "EMAIL_USE_SSL",
    "EMAIL_DEFAULT_FROM",
    "EMAIL_REPLY_TO",
]


@receiver(config_updated)
def constance_updated(sender, key, old_value, new_value, **kwargs):
    from .dynamic_settings import CONSTANCE_DATABASE_PREFIX

    parsed_key = key.replace(CONSTANCE_DATABASE_PREFIX, "")
    if parsed_key in EMAIL_SETTINGS:
        globals()[parsed_key] = new_value


EMAIL_ENABLED = get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool)
EMAIL_HOST = get_from_env("EMAIL_HOST", optional=True)
EMAIL_PORT = get_from_env("EMAIL_PORT", 25, type_cast=int)
EMAIL_HOST_USER = get_from_env("EMAIL_HOST_USER", optional=True)
EMAIL_HOST_PASSWORD = get_from_env("EMAIL_HOST_PASSWORD", optional=True)
EMAIL_USE_TLS = get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool)
EMAIL_USE_SSL = get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool)
DEFAULT_FROM_EMAIL = get_from_env("EMAIL_DEFAULT_FROM", get_from_env("DEFAULT_FROM_EMAIL", "root@localhost"))
EMAIL_REPLY_TO = get_from_env("EMAIL_REPLY_TO", "")

# TODO: Temporary
EMAIL_REPORTS_ENABLED: bool = get_from_env("EMAIL_REPORTS_ENABLED", False, type_cast=str_to_bool)
