from django.conf import settings

from cryptography.fernet import Fernet
from functools import lru_cache
from django.core.exceptions import ImproperlyConfigured


@lru_cache(maxsize=1)
def get_crypter():
    try:
        crypter = Fernet(settings.ENCRYPTION_SECRET_KEY)
    except Exception:
        raise ImproperlyConfigured("SECRET_KEY is not set or is invalid.")

    return crypter


def decrypt(value: str) -> str:
    crypter = get_crypter()
    return crypter.decrypt(value.encode()).decode()


def encrypt(value: str) -> str:
    crypter = get_crypter()
    return crypter.encrypt(value.encode()).decode()
