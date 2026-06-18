"""Constants and small helpers shared across the GitHub callback modules.

These were previously inlined in ``posthog.api.integration`` and
``posthog.api.user_integration``. Grouping them avoids duplication and keeps
the callback modules small.
"""

import re

from django.conf import settings

# Server-side state cache used by the personal GitHub linking flow (the install
# callback and the OAuth-only fast paths). Keys are written when a flow starts
# and consumed when GitHub redirects back to us.
GITHUB_INSTALL_STATE_CACHE_PREFIX = "github_user_install_state:"
GITHUB_INSTALL_STATE_TTL_SECONDS = 10 * 60

# Native deep link the mobile app (apps/mobile) registers as the OAuth return
# URL. The in-app browser (ASWebAuthenticationSession / Custom Tabs) closes and
# returns control to the app when the callback 302s here.
MOBILE_GITHUB_CALLBACK_URL = "posthog://github/callback"

# ``connect_from`` values for first-party clients that use the lightweight app
# linking flow (OAuth-only when the team already has the GitHub App installed,
# otherwise discover/install) and return to a client-specific destination.
APP_CONNECT_FROM_VALUES = ("posthog_code", "posthog_mobile")

# GitHub App installation IDs are always positive integers. Reject anything else
# before it touches URL construction.
_GITHUB_INSTALLATION_ID_RE = re.compile(r"\d{1,20}")


def github_oauth_redirect_uri() -> str:
    return f"{settings.SITE_URL.rstrip('/')}/complete/github-link/"


def is_valid_github_installation_id(value: object) -> bool:
    return value is not None and bool(_GITHUB_INSTALLATION_ID_RE.fullmatch(str(value)))
