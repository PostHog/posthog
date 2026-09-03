"""POST /provisioning/account_requests — onboard a new or existing user and
return either an auth code (new user) or a redirect URL (existing user).

The check order here is part of the observable wire behavior (which error a
request with several problems gets, and whether it consumes partner quota), so
the checks run explicitly in the handler rather than via DRF's auth/permission
hooks: CIMD throttle → partner identification → body validation → partner
capability → partner rate limit → PKCE validation.
"""

from __future__ import annotations

from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.models.user import User
from posthog.scopes import effective_ceiling

from ee.api.agentic_provisioning.accounts import handle_existing_user, handle_new_user
from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.authentication import CLIENT_NOT_REGISTERED_MESSAGE, ProvisioningAuthentication
from ee.api.agentic_provisioning.constants import CODE_CHALLENGE_RE
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.ratelimits import Budget, rate_limited
from ee.api.agentic_provisioning.serializers import AccountRequestSerializer
from ee.api.agentic_provisioning.throttling import CIMDRegistrationThrottle
from ee.api.agentic_provisioning.views.base import ProvisioningAPIView


class AccountRequestsView(ProvisioningAPIView):
    region_proxy_strategy = "body_region"
    partner_throttle_classes = [CIMDRegistrationThrottle]
    # Identifies the partner inline rather than through an authentication class because the
    # region proxy and the request-id echo both need the parsed body alongside the partner.
    authenticates_in_handler = True

    # charge="manual": the partner is only known mid-handler, and a partner refused
    # the capability outright must keep its budget. The tier grid puts this at
    # 10/20/50/100 per hour.
    @rate_limited(
        "account_requests",
        budget=Budget(burst=5, per_hour=10),
        charge="manual",
    )
    def post(self, request: Request) -> Response:
        # --- Identify partner ---
        auth = ProvisioningAuthentication()
        partner = None
        try:
            result = auth.authenticate(request)
            if result:
                _, partner = result
        except AuthenticationFailed as exc:
            # Surface the reason: an unregistered client needs to be told to register, which
            # a flat "authentication failed" does not convey.
            raise ProvisioningError("unauthorized", str(exc.detail), status=401)

        if partner is None:
            raise ProvisioningError("unauthorized", CLIENT_NOT_REGISTERED_MESSAGE, status=401)

        # --- Parse request ---
        data = self.validated_body(AccountRequestSerializer, request)

        request_id = data["id"]
        email = data["email"]

        scopes = data["scopes"]
        if not scopes:
            # Resolve the default before any consent state is created, so the consent
            # page displays exactly what the token exchange will later grant. Matches
            # /authorize: an empty app ceiling resolves to the unprivileged set.
            scopes = sorted(effective_ceiling(partner.ceiling_scopes))
        configuration = data["configuration"]

        if not partner.provisioning.can_create_accounts:
            capture_provisioning_event("account_request", "error", error_code="account_creation_disabled")
            raise ProvisioningError("forbidden", "Account creation is not enabled for this partner", status=403)

        self.charge_rate_limit(request, partner)

        # PKCE: capture code_challenge for later verification
        code_challenge = data["code_challenge"]
        code_challenge_method = data["code_challenge_method"]
        if code_challenge and code_challenge_method != "S256":
            raise ProvisioningError("invalid_request", "Only S256 code_challenge_method is supported")
        if code_challenge and (
            len(code_challenge) < 43 or len(code_challenge) > 128 or not CODE_CHALLENGE_RE.fullmatch(code_challenge)
        ):
            raise ProvisioningError(
                "invalid_request", "code_challenge must be 43-128 characters using base64url charset"
            )

        region = (configuration.get("region") or "US").upper()

        existing_user = User.objects.filter(email=email).first()

        if existing_user:
            return Response(
                handle_existing_user(
                    request_id,
                    existing_user,
                    scopes,
                    region=region,
                    partner=partner,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                )
            )

        return Response(
            handle_new_user(
                request_id,
                data,
                email,
                scopes,
                region=region,
                partner=partner,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
            )
        )
