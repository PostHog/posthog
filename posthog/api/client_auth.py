from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

from django.core.cache import cache
from django.http import JsonResponse
from rest_framework.request import Request
from rest_framework.decorators import action
from rest_framework import viewsets, permissions, exceptions, serializers

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import User

from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from posthog.models.api_scopes import ALL_API_SCOPES

DEFAULT_CLIENT_AUTHENTICATION_TIME = timedelta(days=7)


class ClientAuthenticationUserRateThrottle(UserRateThrottle):
    scope = "client_authentication_user"
    rate = "5/minute"


class ClientAuthenticationAnonCheckRateThrottle(AnonRateThrottle):
    scope = "client_authentication_check"
    rate = "20/minute"  # Clients should check no more than once every 10 seconds


class ClientAuthenticationAnonStartRateThrottle(AnonRateThrottle):
    scope = "client_authentication"
    rate = "3/minute"


class ConfirmAuthSerializer(serializers.Serializer):
    code: serializers.CharField = serializers.CharField(max_length=128, required=True)
    verification: serializers.CharField = serializers.CharField(max_length=128, required=True)
    scopes: serializers.ListField = serializers.ListField(child=serializers.CharField(), required=False)

    def validate_scopes(self, value):
        for scope in value:
            if scope not in ALL_API_SCOPES:
                raise serializers.ValidationError(f"Invalid scope: {scope}")

        return value


def start_client_auth_flow() -> tuple[str, str]:
    code = str(uuid4())
    verification = str(uuid4())

    cache.set(f"client-authorization/flows/{code}", verification, timeout=60 * 5)  # 5 minute timeout

    return (code, verification)


def confirm_client_auth_flow(code: str, verification: str, user: User, scopes: list[str]) -> str:
    known_verification = cache.get(f"client-authorization/flows/{code}")

    if not known_verification:
        raise exceptions.ValidationError({"code": "Code invalid or expired"})

    if known_verification != verification:
        raise exceptions.ValidationError({"code": "Something went wrong. Please restart the flow"})

    known_verification = cache.delete(f"client-authorization/flows/{code}")

    access_token = encode_jwt(
        {"id": user.id},
        DEFAULT_CLIENT_AUTHENTICATION_TIME,
        PosthogJwtAudience.CLIENT,
        scopes=scopes,
    )

    cache.set(f"client-authorization/tokens/{code}", access_token, timeout=60)

    return access_token


class ClientAuthorizationViewset(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    queryset = User.objects.none()
    throttle_classes = [ClientAuthenticationUserRateThrottle]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> JsonResponse:
        code = request.GET.get("code")

        if not code:
            raise exceptions.ValidationError({"code": "Missing code"})

        verification = cache.get(f"client-authorization/flows/{code}")

        if not verification:
            raise exceptions.ValidationError({"code": "Code invalid or expired"})

        return JsonResponse({"code": code, "verification": verification})

    @action(methods=["POST"], detail=False)
    def confirm(self, request: Request, *args, **kwargs) -> JsonResponse:
        serializer = ConfirmAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        confirm_client_auth_flow(data["code"], data["verification"], cast(User, request.user), data["scopes"])

        return JsonResponse({"status": "authorized"})

    @action(
        methods=["GET", "POST"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
        throttle_classes=[ClientAuthenticationAnonStartRateThrottle],
    )
    def start(self, request: Request, *args, **kwargs) -> JsonResponse:
        code, _ = start_client_auth_flow()

        return JsonResponse({"code": code})

    @action(
        methods=["GET"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
        throttle_classes=[ClientAuthenticationAnonCheckRateThrottle],
    )
    def check(self, request: Request, *args, **kwargs) -> JsonResponse:
        code = request.GET.get("code")

        secret = cache.get(f"client-authorization/flows/{code}")
        access_token = cache.get(f"client-authorization/tokens/{code}")

        if access_token:
            # We delete it so it can only be given out once
            cache.delete(f"client-authorization/tokens/{code}")

        status = "missing"

        if secret:
            status = "pending"

        if access_token:
            status = "authorized"

        return JsonResponse({"status": status, "access_token": access_token})
