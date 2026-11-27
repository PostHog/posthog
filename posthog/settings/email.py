import os

from posthog.settings.access import SECRET_KEY
from posthog.settings.utils import get_from_env, get_list, str_to_bool

POSTHOG_TRANSACTIONAL_EMAIL_API_KEY: str = get_from_env("POSTHOG_TRANSACTIONAL_EMAIL_API_KEY", "")

MESSAGING_HASH_SALT: str = os.getenv("MESSAGING_HASH_SALT") or SECRET_KEY
MESSAGING_HASH_SALT_FALLBACKS: list[str] = [
    salt for salt in get_list(os.getenv("MESSAGING_HASH_SALT_FALLBACKS", "")) if salt
]

# Overrides Django's built-in EMAIL_* settings of the same names.
EMAIL_ENABLED: bool = get_from_env("EMAIL_ENABLED", True, type_cast=str_to_bool)
EMAIL_HOST: str = get_from_env("EMAIL_HOST", "")
EMAIL_PORT: int = get_from_env("EMAIL_PORT", 25, type_cast=int)
EMAIL_HOST_USER: str = get_from_env("EMAIL_HOST_USER", "")
EMAIL_USE_TLS: bool = get_from_env("EMAIL_USE_TLS", False, type_cast=str_to_bool)
EMAIL_USE_SSL: bool = get_from_env("EMAIL_USE_SSL", False, type_cast=str_to_bool)
EMAIL_DEFAULT_FROM: str = get_from_env("EMAIL_DEFAULT_FROM", get_from_env("DEFAULT_FROM_EMAIL", "root@localhost"))
EMAIL_REPLY_TO: str = get_from_env("EMAIL_REPLY_TO", "")
EMAIL_TIMEOUT: int = get_from_env("EMAIL_TIMEOUT", 30, type_cast=int)
