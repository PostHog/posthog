"""Rate limit introspection: a partner's derived tier and effective budgets.

The caller has to prove it controls the partner, either with a bearer token or
with the client authentication the token endpoint already takes (a signed
assertion or a client secret). A bare client_id only identifies a public
partner, so honoring it here would hand every caller that partner's tier and
live headroom, and spend its introspection budget in the process. A public
partner reads its own limits with the bearer it holds after its token exchange.

POST rather than GET because client authentication rides the form body, which a
GET has nowhere to carry.
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
    # A bearer only exists in the region that minted it, so a token from the other
    # region has to proxy rather than 401 here.
    region_proxy_strategy = "bearer_lookup"

    @rate_limited("limits_reads", charge="manual")
    def post(self, request: Request) -> Response:
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
            if not app.provisioning.active:
                raise ProvisioningError("unauthorized", "Partner is deactivated", status=401)
            return app

        try:
            result = ProvisioningAuthentication().authenticate(request)
        except AuthenticationFailed as exc:
            raise ProvisioningError("unauthorized", str(exc.detail), status=401)
        if result is None:
            raise ProvisioningError("unauthorized", CLIENT_NOT_REGISTERED_MESSAGE, status=401)

        partner = result[1]
        # A public partner presents a client_id anyone can send, which identifies it
        # without proving the caller is it. Its bearer does.
        if not partner.requires_client_authentication:
            raise ProvisioningError("unauthorized", "This client must authenticate with a bearer token", status=401)
        return partner
