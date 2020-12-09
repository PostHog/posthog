from django.conf import settings


def is_ee_enabled() -> bool:
    return settings.EE_ENABLED
