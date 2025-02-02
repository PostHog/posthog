import os

from posthog.settings import get_list

"""
We sometimes need to block certain email domains from being used in our application.
This is a list of domains that we will block at registration and login.
It should be a comma-separated list of domains, e.g. "email.io,posthog.com"
It isn't intended to be large, so we can just load it into memory.
"""
EMAIL_DOMAIN_BLOCKLIST = get_list(os.getenv("EMAIL_DOMAIN_BLOCKLIST", ""))
