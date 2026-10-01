import os

from posthog.settings.access import SECRET_KEY
from posthog.settings.utils import get_from_env, get_list

MESSAGING_HASH_SALT: str = os.getenv("MESSAGING_HASH_SALT") or SECRET_KEY
MESSAGING_HASH_SALT_FALLBACKS: list[str] = [
    salt for salt in get_list(os.getenv("MESSAGING_HASH_SALT_FALLBACKS", "")) if salt
]

CUSTOMER_IO_API_KEY: str = get_from_env("CUSTOMER_IO_API_KEY", "", type_cast=str)
CUSTOMER_IO_API_URL: str = get_from_env("CUSTOMER_IO_API_URL", "https://api-eu.customer.io", type_cast=str)
