"""Bearer authentication for the Stripe provisioning resource endpoints.

The only accepted identity is the Stripe orchestrator: tokens issued to the
Stripe Projects OAuth app (resolved by
``settings.STRIPE_POSTHOG_OAUTH_CLIENT_ID``). Tokens bound to any other
application are rejected outright. The Stripe app row may or may not be
flagged as a provisioning partner in the database; both states are honored - a
partner-flagged row additionally enforces ``provisioning_active`` and
``provisioning_can_provision_resources``.
"""

from __future__ import annotations

from django.utils import timezone

from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request

from posthog.models.oauth import OAuthAccessToken, find_oauth_access_token
from posthog.models.user import User

from ee.partners.stripe.api.provisioning.core import is_stripe_oauth_app
from ee.partners.stripe.api.provisioning.exceptions import SpecError


class StripeBearerAuthentication(BaseAuthentication):
    """Authenticate the Stripe orchestrator via an OAuth bearer token.

    Returns ``(user, access_token)`` so views read the token off ``request.auth``.
    Raises :class:`SpecError` (rendered in the view's envelope) on failure.
    """

    def authenticate(self, request: Request) -> tuple[User | None, OAuthAccessToken]:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            raise SpecError("unauthorized", "Missing bearer token", status=401)

        token_value = auth_header[len("Bearer ") :].strip()
        if not token_value:
            raise SpecError("unauthorized", "Missing bearer token", status=401)

        access_token = find_oauth_access_token(token_value)
        if access_token is None:
            raise SpecError("unauthorized", "Invalid access token", status=401)

        if access_token.expires and access_token.expires < timezone.now():
            raise SpecError("unauthorized", "Access token expired", status=401)

        # This namespace serves exactly one caller. A token minted for any other
        # application - including other provisioning partners - must fail here;
        # partner-generic traffic belongs to the legacy provisioning surface.
        app = access_token.application
        if app is None or not is_stripe_oauth_app(app):
            raise SpecError("unauthorized", "Authentication failed", status=401)

        if app.is_provisioning_partner:
            if not app.provisioning_active:
                raise SpecError("unauthorized", "Partner is deactivated", status=401)
            if not app.provisioning_can_provision_resources:
                raise SpecError("forbidden", "Resource provisioning not enabled for this partner", status=403)

        return access_token.user, access_token

    def authenticate_header(self, request: Request) -> str:
        return "Bearer"
