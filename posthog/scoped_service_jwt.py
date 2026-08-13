"""Scoped JWTs for service-to-service calls.

The blessed alternative to INTERNAL_API_SECRET (see .agents/security.md, "Don't extend
INTERNAL_API_SECRET to new service-to-service calls"): instead of a stored fleet-wide
credential, the caller mints a short-lived token pinned to one team and operation, signed
with a key only that caller/callee pair holds. A leaked token reaches one team for minutes;
a leaked key reaches one surface, not the fleet.

Each relationship declares a ScopedServiceJwtPurpose (audience + its own settings key) and
either mints from it (Django as caller) or guards a DRF view with a
ScopedServiceJWTAuthentication subclass (Django as callee). Existing hand-rolled
incarnations of this pattern predate this module: reschedule_parked
(posthog/plugins/plugin_server_api.py) and recording-api
(posthog/session_recordings/recordings/recording_api_jwt.py).
"""

import logging
from dataclasses import field
from datetime import timedelta
from typing import Any, ClassVar

from django.apps import apps
from django.conf import settings

import jwt as pyjwt
from rest_framework import authentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from posthog.auth import InternalAPIUser
from posthog.dataclasses import frozen
from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.settings.utils import get_list

logger = logging.getLogger(__name__)

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
        return [key for key in get_list(getattr(settings, self.settings_name, "") or "") if key]

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


def _team_id_from_url(request: Request) -> str | None:
    parser_context = getattr(request, "parser_context", None)
    if isinstance(parser_context, dict):
        kwargs = parser_context.get("kwargs")
        if isinstance(kwargs, dict) and kwargs.get("team_id") is not None:
            return str(kwargs["team_id"])

    django_request = getattr(request, "_request", request)
    resolver_match = getattr(django_request, "resolver_match", None)
    if resolver_match and getattr(resolver_match, "kwargs", None):
        team_id = resolver_match.kwargs.get("team_id")
        if team_id is not None:
            return str(team_id)

    return None


class ScopedServiceJWTAuthentication(authentication.BaseAuthentication):
    """DRF authentication for internal routes called by other PostHog services.

    Subclass per purpose:

        class ConversationsTicketJWTAuthentication(ScopedServiceJWTAuthentication):
            purpose = CONVERSATIONS_TICKETS_PURPOSE

    The request authenticates as a synthetic InternalAPIUser bound to the token's team.
    When the URL carries a team_id, the token's team_id claim must match it, so a token
    minted for one team can never read another's data even if both hit the same route.

    require_team=False is for fleet-scoped purposes (cron-style calls with no team in the
    URL or claims); team-scoped purposes must keep the default so a token without a team
    claim fails closed instead of authenticating unscoped.
    """

    purpose: ClassVar[ScopedServiceJwtPurpose]
    require_team: ClassVar[bool] = True

    def authenticate(self, request: Request) -> tuple[Any, Any] | None:
        header = authentication.get_authorization_header(request).split()
        # No bearer header: return None (not raise) so the view's other authenticators,
        # if any, still get their turn.
        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2:
            raise AuthenticationFailed("Invalid Authorization header.")

        if not self.purpose.enabled():
            # Fail closed at request time rather than startup: most processes never serve
            # these routes and never get the secret injected, so a startup check would
            # wrongly crash them (same reasoning as InternalAPIAuthentication).
            logger.error(
                "Scoped service JWT authentication attempted without configured secret",
                extra={"path": request.path, "settings_name": self.purpose.settings_name},
            )
            raise AuthenticationFailed("Service token authentication is not configured.")

        try:
            claims = self.purpose.verify(header[1].decode())
        except pyjwt.PyJWTError:
            raise AuthenticationFailed("Invalid or expired service token.")

        return self._authenticate_claims(request, claims)

    def _authenticate_claims(self, request: Request, claims: dict[str, Any]) -> tuple[Any, Any]:
        claim_team_id = claims.get("team_id")

        if claim_team_id is None:
            if self.require_team:
                raise AuthenticationFailed("Service token is missing its team claim.")
            return InternalAPIUser(), None

        url_team_id = _team_id_from_url(request)
        if url_team_id is not None and str(claim_team_id) != url_team_id:
            raise AuthenticationFailed("Service token team does not match the requested team.")

        Team = apps.get_model(app_label="posthog", model_name="Team")
        try:
            team = Team.objects.only("id", "organization_id").get(id=claim_team_id)
        except (Team.DoesNotExist, ValueError, TypeError):
            raise AuthenticationFailed("Invalid service token team.")

        return InternalAPIUser(current_organization_id=team.organization_id, current_team_id=team.id), None
