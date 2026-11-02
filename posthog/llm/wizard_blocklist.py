"""Shared values for the AI gateway checks that refuse a blocked identity.

The security access rules (`products/security`) decide who is blocked. This module
holds what every gateway call site shares: which scopes carry gateway access, and
the message a blocked identity sees.
"""

from posthog.scopes import PRIVILEGED_SCOPES

# Wider than the two privileged names: the legacy gateway authenticates a bare
# `*`, which an app with an empty ceiling is still granted verbatim.
GATEWAY_BEARING_SCOPES = frozenset(PRIVILEGED_SCOPES | {"*"})

# One string for every surface: the wizard shows it to the user, so a ban reads
# the same whether it lands at consent, at the mint, or on a query.
WIZARD_BLOCKED_DETAIL = (
    "This account is blocked from the PostHog AI gateway for suspected abuse. "
    "Contact wizard@posthog.com if you believe this is a mistake."
)
