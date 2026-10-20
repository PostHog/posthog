import os

from posthog.settings.access import SECRET_KEY
from posthog.settings.utils import get_list

MESSAGING_HASH_SALT: str = os.getenv("MESSAGING_HASH_SALT") or SECRET_KEY
MESSAGING_HASH_SALT_FALLBACKS: list[str] = [
    salt for salt in get_list(os.getenv("MESSAGING_HASH_SALT_FALLBACKS", "")) if salt
]

POSTHOG_TRANSACTIONAL_EMAIL_API_HOST: str = os.getenv("POSTHOG_TRANSACTIONAL_EMAIL_API_HOST", "https://us.posthog.com")
POSTHOG_TRANSACTIONAL_EMAIL_PROJECT_ID: int = int(os.getenv("POSTHOG_TRANSACTIONAL_EMAIL_PROJECT_ID") or "0")
POSTHOG_TRANSACTIONAL_EMAIL_API_KEY: str = os.getenv("POSTHOG_TRANSACTIONAL_EMAIL_API_KEY", "")
