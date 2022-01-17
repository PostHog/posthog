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
    if key in EMAIL_SETTINGS:
        globals()[key] = new_value


# TODO: Temporary
EMAIL_REPORTS_ENABLED: bool = get_from_env("EMAIL_REPORTS_ENABLED", False, type_cast=str_to_bool)
