from posthog.settings.access import SECRET_KEY
from posthog.settings.utils import get_list, secret_env

MESSAGING_HASH_SALT: str = secret_env("MESSAGING_HASH_SALT") or SECRET_KEY
MESSAGING_HASH_SALT_FALLBACKS: list[str] = [
    salt for salt in get_list(secret_env("MESSAGING_HASH_SALT_FALLBACKS", "")) if salt
]
