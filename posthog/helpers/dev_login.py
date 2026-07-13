from django.conf import settings


def is_dev_login_allowed() -> bool:
    return settings.DEBUG and settings.ALLOW_DEV_LOGIN
