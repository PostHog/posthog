import os

from posthog.settings.utils import get_list

# US-only, PEM, multiple keys allowed (comma-separated)
WEB_BOT_AUTH_PRIVATE_KEYS_ENV_VAR_PRESENT = "WEB_BOT_AUTH_PRIVATE_KEYS" in os.environ
WEB_BOT_AUTH_PRIVATE_KEYS = get_list(os.getenv("WEB_BOT_AUTH_PRIVATE_KEYS", ""))
