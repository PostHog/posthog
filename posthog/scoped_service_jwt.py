"""Scoped JWTs for service-to-service calls.

The blessed alternative to INTERNAL_API_SECRET (see .agents/security.md, "Don't extend
INTERNAL_API_SECRET to new service-to-service calls"): instead of a stored fleet-wide
credential, the caller mints a short-lived token pinned to one team and operation, signed
with a key only that caller/callee pair holds. A leaked token reaches one team for minutes;
a leaked key reaches one surface, not the fleet.

Each relationship declares a ScopedServiceJwtPurpose (audience + its own settings key) and
either mints from it (Django as caller) or guards a DRF view with a
ScopedServiceJWTAuthentication subclass (Django as callee; lives in posthog.auth with the
other authentication classes). This module must stay importable before the Django app
registry is ready: modules loaded at startup (e.g. posthog.plugins.plugin_server_api)
declare purposes at module level, so nothing here may import models or DRF.
"""

from dataclasses import field
from datetime import timedelta
from typing import Any

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt

DEFAULT_SERVICE_TOKEN_TTL = timedelta(minutes=5)


@frozen
class ScopedServiceJwtPurpose:
    """One caller→callee auth relationship: the audience names the callee surface, and
    settings_name is the env var holding that pair's dedicated signing keys (comma-separated,
    newest first, so keys rotate without a coordinated deploy). Never share a key between
    purposes; the per-purpose key is what keeps a leak contained to one surface.
    """

    audience: PosthogJwtAudience
    settings_name: str
    default_ttl: timedelta = field(default=DEFAULT_SERVICE_TOKEN_TTL)

    def signing_keys(self) -> list[str]:
        value = getattr(settings, self.settings_name, "") or ""
        # Settings may hold either the raw comma-separated string (RECORDING_API_JWT_SECRET) or a
        # list already parsed with get_list at load time (WORKFLOWS_RESCHEDULE_JWT_SECRETS). The
        # string parse matches get_list, inlined because importing posthog.settings here would pull
        # the whole settings package into posthog.auth's import graph.
        if isinstance(value, list | tuple):
            return [key.strip() for key in value if key and key.strip()]
        return [key.strip() for key in value.split(",") if key.strip()]

    def enabled(self) -> bool:
        """False until the purpose's secret is provisioned. Callers use this to fall back to
        their legacy auth path, so the scheme rolls out per environment without a flag."""
        return bool(self.signing_keys())

    def mint(self, claims: dict[str, Any], ttl: timedelta | None = None) -> str:
        """Mint a token carrying `claims` (e.g. team_id and the target entity's id). Signs with
        the newest key; verifiers try the full set, so rotation never breaks in-flight calls."""
        keys = self.signing_keys()
        if not keys:
            raise RuntimeError(f"{self.settings_name} is not configured")
        return encode_jwt(claims, ttl or self.default_ttl, self.audience, signing_key=keys[0])

    def verify(self, token: str) -> dict[str, Any]:
        """Decode and validate signature, expiry, and audience. Raises pyjwt exceptions on bad
        tokens and RuntimeError when the purpose is unprovisioned (misconfiguration, not a bad
        token, so callers can distinguish the two)."""
        keys = self.signing_keys()
        if not keys:
            raise RuntimeError(f"{self.settings_name} is not configured")
        return decode_jwt(token, self.audience, verification_keys=keys)
