"""Browser endpoints take the session only, so no long-lived key can mint. The CLI never holds
a PostHog credential: the browser authorizes a PKCE challenge and hands a one-time code to
the CLI's loopback listener, which exchanges it for a token.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse
from rest_framework import permissions, status, viewsets
from rest_framework.authentication import BaseAuthentication
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.auth import SessionAuthentication
from posthog.helpers.impersonation import is_impersonated
from posthog.models.user import User
from posthog.permissions import TimeSensitiveActionPermission
from posthog.rate_limit import IPThrottle

from ..facade import api
from ..facade.contracts import DevTokenRefused
from ..facade.enums import DevTokenClient
from .serializers import (
    CliAuthorizedSerializer,
    CliAuthorizeSerializer,
    CliExchangeSerializer,
    DevTeamUsageSerializer,
    DevTokenRefusalSerializer,
    DevTokenRevokedSerializer,
    DevTokenRevokeSerializer,
    DevTokenSerializer,
    DevTokenStatusRequestSerializer,
    DevTokenUsageSerializer,
    MintedDevTokenSerializer,
)

if TYPE_CHECKING:
    from rest_framework.permissions import _SupportsHasPermission

_REFUSAL = OpenApiResponse(response=DevTokenRefusalSerializer)


class DevTokenMintThrottle(UserRateThrottle):
    scope = "ai_gateway_dev_token_mint"

    def get_rate(self) -> str:
        return f"{int(settings.DEV_GATEWAY_MINTS_PER_HOUR)}/hour"


class DevTokenExchangeIPThrottle(IPThrottle):
    scope = "ai_gateway_dev_token_exchange_ip"
    rate = "30/minute"


def _refusal(refused: DevTokenRefused) -> Response:
    return Response(
        DevTokenRefusalSerializer({"code": refused.code, "detail": refused.detail}).data, status=refused.http_status
    )


class DevGatewayTokenViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated, TimeSensitiveActionPermission]
    time_sensitive_exclude_actions = ["revoke", "usage", "team_usage"]
    scope_object = "INTERNAL"

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action in ("create", "authorize_cli"):
            return [DevTokenMintThrottle()]
        if self.action in ("exchange_cli", "token_status"):
            return [DevTokenExchangeIPThrottle()]
        return super().get_throttles()

    def get_authenticators(self) -> list[BaseAuthentication]:
        # The PKCE verifier or the bearer authenticates these; DRF resolves authenticators before
        # `self.action` is set, so match on the path.
        if self.request is not None and self.request.path.rstrip("/").endswith(("/cli_exchange", "/token_status")):
            return []
        return super().get_authenticators()

    def get_permissions(self) -> Sequence["_SupportsHasPermission"]:
        if self.action in ("exchange_cli", "token_status"):
            return [permissions.AllowAny()]
        return super().get_permissions()

    def _caller_refusal(self, request: Request) -> DevTokenRefused | None:
        if is_impersonated(request):
            return DevTokenRefused("impersonated", "Developer mode isn't available while impersonating a user.", 403)
        return api.eligibility_refusal(cast(User, request.user))

    @validated_request(
        responses={200: OpenApiResponse(response=DevTokenUsageSerializer), 403: _REFUSAL, 503: _REFUSAL},
        summary="List your live developer mode tokens and today's usage",
    )
    @action(detail=False, methods=["get"], url_path="usage")
    def usage(self, request: Request) -> Response:
        refused = self._caller_refusal(request)
        if refused is not None:
            return _refusal(refused)
        return Response(DevTokenUsageSerializer(api.dev_token_usage(cast(User, request.user))).data)

    @validated_request(
        responses={200: OpenApiResponse(response=DevTeamUsageSerializer), 403: _REFUSAL, 503: _REFUSAL},
        summary="Developer mode minting and spend per user over the last 30 days",
    )
    @action(detail=False, methods=["get"], url_path="team_usage")
    def team_usage(self, request: Request) -> Response:
        if is_impersonated(request):
            return _refusal(
                DevTokenRefused("impersonated", "Developer mode isn't available while impersonating a user.", 403)
            )
        try:
            usage = api.dev_team_usage(cast(User, request.user))
        except DevTokenRefused as e:
            return _refusal(e)
        return Response(DevTeamUsageSerializer(usage).data)

    @validated_request(
        responses={
            201: OpenApiResponse(response=MintedDevTokenSerializer),
            403: _REFUSAL,
            429: _REFUSAL,
            503: _REFUSAL,
        },
        summary="Create a developer mode token attributed to you",
    )
    def create(self, request: Request) -> Response:
        refused = self._caller_refusal(request)
        if refused is not None:
            return _refusal(refused)
        try:
            minted = api.mint_dev_token(cast(User, request.user), DevTokenClient.WEB)
        except DevTokenRefused as e:
            return _refusal(e)
        return Response(MintedDevTokenSerializer(minted).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=DevTokenRevokeSerializer,
        responses={
            200: OpenApiResponse(response=DevTokenRevokedSerializer),
            403: _REFUSAL,
            404: _REFUSAL,
            503: _REFUSAL,
        },
        summary="Revoke one or all of your developer mode tokens",
    )
    @action(detail=False, methods=["post"], url_path="revoke")
    def revoke(self, request: Request) -> Response:
        if is_impersonated(request):
            return _refusal(
                DevTokenRefused("impersonated", "Developer mode isn't available while impersonating a user.", 403)
            )
        token_id = request.validated_data.get("id")
        try:
            count = api.revoke_dev_tokens(cast(User, request.user), str(token_id) if token_id else None)
        except DevTokenRefused as e:
            return _refusal(e)
        return Response(DevTokenRevokedSerializer({"revoked_count": count}).data)

    @validated_request(
        request_serializer=CliAuthorizeSerializer,
        responses={200: OpenApiResponse(response=CliAuthorizedSerializer), 403: _REFUSAL, 503: _REFUSAL},
        summary="Authorize a CLI login by its PKCE challenge",
    )
    @action(detail=False, methods=["post"], url_path="cli_authorize")
    def authorize_cli(self, request: Request) -> Response:
        refused = self._caller_refusal(request)
        if refused is not None:
            return _refusal(refused)
        code = api.authorize_cli(cast(User, request.user), request.validated_data["code_challenge"])
        return Response(CliAuthorizedSerializer({"code": code}).data)

    @validated_request(
        request_serializer=CliExchangeSerializer,
        responses={
            201: OpenApiResponse(response=MintedDevTokenSerializer),
            400: _REFUSAL,
            403: _REFUSAL,
            429: _REFUSAL,
        },
        summary="Exchange a CLI authorization code for a developer mode token",
    )
    @action(detail=False, methods=["post"], url_path="cli_exchange")
    def exchange_cli(self, request: Request) -> Response:
        try:
            minted = api.exchange_cli_code(request.validated_data["code"], request.validated_data["code_verifier"])
        except DevTokenRefused as e:
            return _refusal(e)
        return Response(MintedDevTokenSerializer(minted).data, status=status.HTTP_201_CREATED)

    @validated_request(
        request_serializer=DevTokenStatusRequestSerializer,
        responses={200: OpenApiResponse(response=DevTokenSerializer), 404: _REFUSAL, 503: _REFUSAL},
        summary="Look up a developer mode token's status and budget left by its bearer",
    )
    @action(detail=False, methods=["post"], url_path="token_status")
    def token_status(self, request: Request) -> Response:
        try:
            token = api.dev_token_status(request.validated_data["token"])
        except DevTokenRefused as e:
            return _refusal(e)
        return Response(DevTokenSerializer(token).data)
