from typing import cast

from django.db import models

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.services.terminal import TerminalSandboxService, TerminalSandboxUnavailable
from posthog.auth import SessionAuthentication
from posthog.decorators import disallow_if_impersonated
from posthog.models import User
from posthog.ph_client import feature_enabled_or_false


class TerminalSandboxSize(models.TextChoices):
    SMALL = "small", "Small"
    BALANCED = "balanced", "Balanced"
    LARGE = "large", "Large"
    HIGH_MEMORY = "high_memory", "High memory"


class TerminalSandboxRequestSerializer(serializers.Serializer):
    sandbox_size = serializers.ChoiceField(
        choices=TerminalSandboxSize.choices,
        default=TerminalSandboxSize.SMALL,
        help_text="Compute size for the Modal sandbox.",
    )


class TerminalSandboxSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Opaque terminal session identifier.")
    url = serializers.URLField(help_text="Authenticated Modal connection endpoint.")
    token = serializers.CharField(help_text="Connection token scoped to this sandbox.")
    sandbox_size = serializers.ChoiceField(choices=TerminalSandboxSize.choices, help_text="Provisioned sandbox size.")


class TerminalSandboxThrottle(UserRateThrottle):
    scope = "terminal_sandbox"
    rate = "6/minute"


@extend_schema(extensions={"x-product": ["core"]})
class TerminalViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "INTERNAL"
    authentication_classes = [SessionAuthentication]
    serializer_class = TerminalSandboxSerializer

    def _service(self, *, starting: bool = False) -> TerminalSandboxService:
        user = cast(User, self.request.user)
        if not isinstance(self.request.successful_authenticator, SessionAuthentication):
            raise PermissionDenied("Sign in to use the terminal.")
        if starting and not feature_enabled_or_false(
            "posthog-terminal", str(user.distinct_id), groups={"organization": str(self.team.organization_id)}
        ):
            raise PermissionDenied("The terminal is not enabled for this account.")
        return TerminalSandboxService(self.team_id, user.id)

    @extend_schema(request=TerminalSandboxRequestSerializer, responses={201: TerminalSandboxSerializer})
    @disallow_if_impersonated()
    def create(self, request: Request, **kwargs: object) -> Response:
        serializer = TerminalSandboxRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        service = self._service(starting=True)
        throttle = TerminalSandboxThrottle()
        if not throttle.allow_request(request, self):
            self.throttled(request, throttle.wait() or 0)
        try:
            result = service.start(serializer.validated_data["sandbox_size"])
        except Exception as error:
            if isinstance(error, APIException):
                raise
            raise TerminalSandboxUnavailable() from error
        response = Response(result, status=201)
        response["Cache-Control"] = "no-store"
        return response

    @extend_schema(responses={204: None})
    @disallow_if_impersonated()
    def destroy(self, request: Request, pk: str, **kwargs: object) -> Response:
        self._service().stop(pk)
        return Response(status=204)
