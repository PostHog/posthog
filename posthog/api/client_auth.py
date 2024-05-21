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


DEFAULT_CLIENT_AUTHENTICATION_TIME = timedelta(days=7)


class ConfirmAuthSerializer(serializers.Serializer):
    code: serializers.CharField = serializers.CharField(max_length=128, required=True)
    verification: serializers.CharField = serializers.CharField(max_length=128, required=True)


class ClientAuthenticationViewset(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    queryset = User.objects.none()

    def list(self, request: Request, *args: Any, **kwargs: Any) -> JsonResponse:
        code = request.GET.get("code")

        if not code:
            raise exceptions.ValidationError({"code": "Missing"})

        verification = cache.get(f"cli-authentication/flows/{code}")

        if not verification:
            raise exceptions.ValidationError({"code": "Invalid or timed out"})

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
            raise exceptions.ValidationError({"code": "Code not found or timed out"})

        if known_verification != given_verification:
            raise exceptions.ValidationError({"code": "Something went wrong. Please restart the flow"})

        known_verification = cache.delete(f"cli-authentication/flows/{code}")

        access_token = encode_jwt(
            {"id": request.user.id},
            DEFAULT_CLIENT_AUTHENTICATION_TIME,
            PosthogJwtAudience.CLIENT,
        )

        cache.set(f"cli-authentication/tokens/{code}", access_token, timeout=60)

        return JsonResponse({"message": "Success! You can close this window now."})

    @action(
        methods=["GET", "POST"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
    )
    def start(self, request: Request, *args, **kwargs) -> JsonResponse:
        # TODO: Figure out a sensible rate limiting here
        code = str(uuid4())
        secret = str(uuid4())

        cache.set(f"cli-authentication/flows/{code}", secret, timeout=60 * 5)  # 5 minute timeout

        return JsonResponse({"code": code})

    @action(
        methods=["GET"],
        detail=False,
        dangerously_get_authenticators=lambda: [],
        dangerously_get_permissions=lambda: [permissions.AllowAny()],
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
            status = "authenticated"

        return JsonResponse({"status": status, "access_token": access_token})
