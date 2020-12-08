from django.conf import settings


def is_ch_enabled() -> bool:
    return settings.EE_ENABLED
