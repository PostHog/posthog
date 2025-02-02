import os

from posthog.settings import get_list

EMAIL_DOMAIN_BLOCKLIST = get_list(os.getenv("EMAIL_DOMAIN_BLOCKLIST", ""))
