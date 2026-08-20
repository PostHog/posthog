import os

from posthog.settings.access import SECRET_KEY
from posthog.settings.utils import get_list

MESSAGING_HASH_SALT: str = os.getenv("MESSAGING_HASH_SALT") or SECRET_KEY
MESSAGING_HASH_SALT_FALLBACKS: list[str] = [
    salt for salt in get_list(os.getenv("MESSAGING_HASH_SALT_FALLBACKS", "")) if salt
]

# Public base URL for the email tracking/webhook endpoints served by the Node CDP API. Must match
# the Node side's CDP_EMAIL_TRACKING_URL so provider webhook URLs shown at setup time route there.
EMAIL_TRACKING_URL: str = os.getenv("EMAIL_TRACKING_URL", "")
