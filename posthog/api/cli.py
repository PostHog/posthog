from datetime import timedelta
from typing import Any
from uuid import uuid4

from django.core.cache import cache
from django.http import JsonResponse
from rest_framework.request import Request
from rest_framework.decorators import action
from rest_framework import viewsets
from django.views.decorators.csrf import csrf_exempt

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import User
from posthog.utils import absolute_uri


class CliAuthenticationViewset(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "INTERNAL"
    queryset = User.objects.none()

    def list(self, request: Request, *args: Any, **kwargs: Any) -> JsonResponse:
        code = request.GET.get("code")

        if not code:
            return JsonResponse({"message": "Please provide a code"})

        secret = cache.get(f"cli-authentication/flows/{code}")

        if not secret:
            return JsonResponse({"message": "Code invalid or timed out"})

        return JsonResponse(
            {
                "message": "Allow access to the CLI? Ensure the token below matches what your CLI says",
                "code": code,
                "confirm": absolute_uri(f"api/login/cli/confirm?code={code}&secret={secret}"),
            }
        )

    @action(methods=["GET"], detail=False)
    def confirm(self, request: Request, *args, **kwargs) -> JsonResponse:
        code = request.GET.get("code")
        given_secret = request.GET.get("secret")

        known_secret = cache.get(f"cli-authentication/flows/{code}")

        if not known_secret:
            return JsonResponse({"message": "Code not found or timed out"})

        if known_secret != given_secret:
            return JsonResponse({"message": "Something went wrong. Please restart the flow"})

        known_secret = cache.delete(f"cli-authentication/flows/{code}")

        access_token = encode_jwt(
            {"id": request.user.id},
            timedelta(hours=8),
            PosthogJwtAudience.CLI,
        )

        cache.set(f"cli-authentication/tokens/{code}", access_token, timeout=60)

        return JsonResponse({"message": "Success! You can close this window now."})


@csrf_exempt
def cli_login_start(request: Request):
    # TODO: Figure out a sensible rate limiting here
    code = str(uuid4())
    secret = str(uuid4())

    cache.set(f"cli-authentication/flows/{code}", secret, timeout=60 * 5)  # 5 minute timeout

    return JsonResponse({"code": code})


@csrf_exempt
def cli_login_check(request: Request):
    # TODO: Sensible rate limiting here
    code = request.GET.get("code")

    secret = cache.get(f"cli-authentication/flows/{code}")
    access_token = cache.get(f"cli-authentication/tokens/{code}")

    if access_token:
        # We delete it so it can only be given out once
        cache.delete(f"cli-authentication/tokens/{code}")

    status = "unknown"

    if secret:
        status = "pending"

    if access_token:
        status = "authenticated"

    return JsonResponse({"status": status, "access_token": access_token})
