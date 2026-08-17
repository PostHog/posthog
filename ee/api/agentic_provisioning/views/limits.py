"""Rate limit introspection: a partner's derived tier and effective budgets.

GET serves bearer holders; POST serves client-authenticated partners (a signed
assertion or client secret rides the form body, the same way the token endpoint
takes it, which a GET has nowhere to carry). Both return the same document, so
a partner can see its limits and current headroom instead of discovering them
through 429s.
"""

from __future__ import annotations

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.authentication import (
    CLIENT_NOT_REGISTERED_MESSAGE,
    BearerTokenError,
    ProvisioningAuthentication,
    resolve_bearer_access_token,
)
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import describe_budgets, rate_limited
from ee.api.agentic_provisioning.views.base import ProvisioningAPIView


class LimitsView(ProvisioningAPIView):
    # The partner arrives by bearer or by client authentication, resolved in the
    # handler so both paths share one endpoint.
    authenticates_in_handler = True

    @rate_limited("limits_reads", charge="manual")
    def get(self, request: Request) -> Response:
        return self._limits_response(request)

    @rate_limited("limits_reads", charge="manual")
    def post(self, request: Request) -> Response:
        return self._limits_response(request)

    def _limits_response(self, request: Request) -> Response:
        partner = self._identify_partner(request)
        self.charge_rate_limit(request, partner)
        return Response(
            {
                "tier": partner.partner_tier,
                "tier_basis": {
                    "client_authentication": partner.token_endpoint_auth_method.value,
                    "attested": partner.organization_id is not None,
                },
                "endpoints": describe_budgets(partner),
            }
        )

    def _identify_partner(self, request: Request) -> OAuthApplication:
        if request.headers.get("Authorization", "").startswith("Bearer "):
            try:
                access_token = resolve_bearer_access_token(request)
            except BearerTokenError as exc:
                raise ProvisioningError("unauthorized", str(exc), status=401)
            app = access_token.application
            if app is None or not app.is_provisioning_partner:
                raise ProvisioningError("unauthorized", "Authentication failed", status=401)
            return app

        try:
            result = ProvisioningAuthentication().authenticate(request)
        except AuthenticationFailed as exc:
            raise ProvisioningError("unauthorized", str(exc.detail), status=401)
        if result is None:
            raise ProvisioningError("unauthorized", CLIENT_NOT_REGISTERED_MESSAGE, status=401)
        return result[1]
