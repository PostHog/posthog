"""Base views for the agentic provisioning API.

Every endpoint in this namespace is a DRF class-based view built on
:class:`ProvisioningAPIView`. Errors raised as :class:`ProvisioningError`
(from views, serializers, authentication, or throttling helpers) render in the
view's declared wire envelope, so DRF's default error shape never leaks out of
these partner-facing endpoints.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.core.exceptions import ImproperlyConfigured

from rest_framework import serializers
from rest_framework.authentication import BaseAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle
from rest_framework.views import APIView

from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.team.team import Team

from ee.api.agentic_provisioning.authentication import GitHubGrantsAuthentication, ProvisioningBearerAuthentication
from ee.api.agentic_provisioning.exceptions import Envelope, ProvisioningError, render_provisioning_error
from ee.api.agentic_provisioning.ratelimits import (
    BudgetDeclaration,
    apply_rate_limit_headers,
    charge_partner,
    partner_for_rate_limiting,
    refund_no_work,
)
from ee.api.agentic_provisioning.region_proxy import RegionProxyMixin
from ee.api.agentic_provisioning.serializers import first_error_message


class ProvisioningAPIView(RegionProxyMixin, APIView):
    """Base for every endpoint in this namespace.

    Errors raised as :class:`ProvisioningError` render in the view's envelope.

    A subclass must either declare ``authentication_classes`` or set
    ``authenticates_in_handler = True``, so an endpoint added later cannot end up
    unauthenticated by inheriting a permissive default. See :meth:`__init_subclass__`.
    """

    authentication_classes: list[type[BaseAuthentication]] = []
    permission_classes: list = []
    error_envelope: ClassVar[Envelope] = "typed"

    # Set by the few endpoints that must authenticate mid-handler rather than through a DRF
    # authentication class: the token endpoint resolves its partner from the grant it is
    # redeeming, and account_requests needs the CIMD registration-pending signal that
    # ProvisioningAuthentication exposes as instance state.
    authenticates_in_handler: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Refuse to define an endpoint that authenticates nobody.

        These endpoints are partner-facing and several act on a partner's behalf without an
        end user, so an accidentally open one would not fail any ordinary test. Making the
        omission a definition-time error means it cannot reach review.
        """
        super().__init_subclass__(**kwargs)
        # Intermediate bases exist to be subclassed and carry no routes of their own.
        if cls.__name__.endswith("APIView"):
            return
        if not cls.authentication_classes and not cls.authenticates_in_handler:
            raise TypeError(
                f"{cls.__name__} declares no authentication_classes. Provisioning endpoints are "
                "partner-facing, so set authentication_classes (for example to "
                "GitHubGrantsAuthentication) or, if it must authenticate inside the "
                "handler, set authenticates_in_handler = True."
            )

    # Provisioning throttles keyed on something DRF has by the time it calls
    # check_throttles (the partner on request.auth, a URL kwarg). These are the
    # only limits that reliably apply here: DEFAULT_THROTTLE_CLASSES is a no-op
    # unless the RATE_LIMIT_ENABLED instance setting is on, and even then it
    # skips authenticated requests that carry no personal API key, which is
    # every bearer-authenticated provisioning call.
    # Flows whose key only appears mid-handler (token exchange, account
    # request partner quota, wizard runs) call the throttling helpers instead.
    partner_throttle_classes: ClassVar[list[type[BaseThrottle]]] = []

    def get_throttles(self) -> list[BaseThrottle]:
        return [*super().get_throttles(), *(throttle() for throttle in self.partner_throttle_classes)]

    def check_throttles(self, request: Request) -> None:
        """Reject on the first throttle that refuses, in the view's wire envelope.

        Short-circuiting means a request already refused by the global per-IP
        limit doesn't also spend partner quota, and partners get the documented
        ``rate_limited`` shape rather than DRF's ``{"detail": ...}``.
        """
        for throttle in self.get_throttles():
            if throttle.allow_request(request, self):
                continue

            wait = throttle.wait()
            raise ProvisioningError(
                "rate_limited",
                getattr(throttle, "error_message", "Rate limit exceeded. Try again later."),
                status=429,
                retry_after=int(wait) if wait else None,
            )

        # Partner bucket charges declared with @rate_limited(charge="auto") on the
        # handler. After the throttles above, so a request they refuse spends nothing.
        for declaration in self._budget_declarations(request).values():
            if declaration.charge != "auto":
                continue
            partner = partner_for_rate_limiting(request)
            if partner is None:
                continue
            key_suffix = declaration.key(request, self) if declaration.key else ""
            charge_partner(
                declaration,
                partner,
                request=request,
                key_suffix=key_suffix,
                resource_id=str(self.kwargs.get("resource_id", "")),
            )

    def _budget_declarations(self, request: Request) -> dict[str, BudgetDeclaration]:
        handler = getattr(self, (request.method or "").lower(), None)
        return getattr(handler, "_provisioning_budgets", {})

    def charge_rate_limit(
        self, request: Request, partner: OAuthApplication, *, endpoint: str | None = None, resource_id: str = ""
    ) -> None:
        """Charge a ``charge="manual"`` budget declared on the current handler.

        ``endpoint`` is only needed when the handler declares more than one
        budget; the declaration itself stays on the decorator, so the policy is
        stated exactly once.
        """
        declarations = self._budget_declarations(request)
        if endpoint is None:
            if len(declarations) != 1:
                raise ImproperlyConfigured(
                    f"{type(self).__name__} declares {len(declarations)} budgets; pass endpoint= to charge_rate_limit"
                )
            declaration = next(iter(declarations.values()))
        else:
            declaration = declarations[endpoint]
        charge_partner(declaration, partner, request=request, resource_id=resource_id)

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ProvisioningError):
            # A rejection that provably did no work costs no quota. The one
            # exception class carries the code, so the refund decision needs no
            # per-endpoint choreography in the handlers.
            refund_no_work(self.request, exc.code)
            return render_provisioning_error(exc, self.error_envelope)
        return super().handle_exception(exc)

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        apply_rate_limit_headers(request, response)
        return response

    def validated_body(
        self,
        serializer_class: type[serializers.Serializer],
        request: Request,
        *,
        resource_id: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Parse the request body, raising the wire-contract ``invalid_request``
        error (never DRF's default shape) when validation fails."""
        serializer = serializer_class(data=request.data, context=context or {})
        if not serializer.is_valid():
            raise ProvisioningError("invalid_request", first_error_message(serializer.errors), resource_id=resource_id)
        return serializer.validated_data


class GitHubGrantsAPIView(ProvisioningAPIView):
    """Base for the GitHub grant endpoints.

    The partner rides ``request.auth``, having proven itself with either a signed
    ``private_key_jwt`` assertion or a verified client secret. A public partner is identified
    only by a client_id anyone can send, so it never reaches these endpoints, and a confidential
    one still needs ``can_use_github_grants`` granted.
    """

    authentication_classes = [GitHubGrantsAuthentication]


class BearerResourceAPIView(ProvisioningAPIView):
    """Base for the bearer-authenticated resource endpoints (status envelope)."""

    error_envelope = "status"
    region_proxy_strategy = "bearer_lookup"
    authentication_classes = [ProvisioningBearerAuthentication]

    def parse_resource_team_id(self, resource_id: str, access_token: OAuthAccessToken) -> int:
        try:
            team_id = int(resource_id)
        except (ValueError, TypeError):
            raise ProvisioningError("invalid_resource_id", "Invalid resource ID", resource_id=resource_id)

        if team_id not in (access_token.scoped_teams or []):
            raise ProvisioningError(
                "forbidden", "Resource not accessible with this token", resource_id=resource_id, status=403
            )
        return team_id

    def get_team(self, team_id: int, resource_id: str) -> Team:
        try:
            return Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise ProvisioningError("not_found", "Resource not found", resource_id=resource_id, status=404)

    def get_scoped_team(self, resource_id: str, access_token: OAuthAccessToken) -> Team:
        """Resolve the resource id to its team, enforcing the token's team scope."""
        return self.get_team(self.parse_resource_team_id(resource_id, access_token), resource_id)
