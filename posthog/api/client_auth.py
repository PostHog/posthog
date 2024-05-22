from datetime import timedelta
from typing import Any
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


class ClientAuthenticationViewset(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    queryset = User.objects.none()
    throttle_classes = [ClientAuthenticationUserRateThrottle]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> JsonResponse:
        code = request.GET.get("code")

        if not code:
            raise exceptions.ValidationError({"code": "Missing code"})

        verification = cache.get(f"cli-authentication/flows/{code}")

        if not verification:
            raise exceptions.ValidationError({"code": "Code invalid or expired"})

        return JsonResponse({"code": code, "verification": verification})

    @action(methods=["POST"], detail=False)
    def confirm(self, request: Request, *args, **kwargs) -> JsonResponse:
        serializer = ConfirmAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        code = data["code"]
        given_verification = data["verification"]
        known_verification = cache.get(f"cli-authentication/flows/{code}")

        if not known_verification:
            raise exceptions.ValidationError({"code": "Code invalid or expired"})

        if known_verification != given_verification:
            raise exceptions.ValidationError({"code": "Something went wrong. Please restart the flow"})

        known_verification = cache.delete(f"cli-authentication/flows/{code}")

        access_token = encode_jwt(
            {"id": request.user.id},
            DEFAULT_CLIENT_AUTHENTICATION_TIME,
            PosthogJwtAudience.CLIENT,
        )

        cache.set(f"cli-authentication/tokens/{code}", access_token, timeout=60)

        return JsonResponse({"status": "authorized"})

    @action(
        methods=["GET", "POST"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
        throttle_classes=[ClientAuthenticationAnonStartRateThrottle],
    )
    def start(self, request: Request, *args, **kwargs) -> JsonResponse:
        code = str(uuid4())
        secret = str(uuid4())

        cache.set(f"cli-authentication/flows/{code}", secret, timeout=60 * 5)  # 5 minute timeout

        return JsonResponse({"code": code})

    @action(
        methods=["GET"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
        throttle_classes=[ClientAuthenticationAnonCheckRateThrottle],
    )
    def check(self, request: Request, *args, **kwargs) -> JsonResponse:
        # TODO: Sensible rate limiting here
        code = request.GET.get("code")

        secret = cache.get(f"cli-authentication/flows/{code}")
        access_token = cache.get(f"cli-authentication/tokens/{code}")

        if access_token:
            # We delete it so it can only be given out once
            cache.delete(f"cli-authentication/tokens/{code}")

        status = "missing"

        if secret:
            status = "pending"

        if access_token:
            status = "authorized"

        return JsonResponse({"status": status, "access_token": access_token})
