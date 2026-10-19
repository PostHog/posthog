from dataclasses import asdict
from uuid import UUID

from django.db import models

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.authentication import get_authorization_header
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request
from posthog.permissions import APIScopePermission
from posthog.rate_limit import ContextSelectionBurstThrottle, ContextSelectionSustainedThrottle

from products.context_layer.backend.facade import selection


class SelectionUnavailable(APIException):
    status_code = 503
    default_detail = "Context selection is busy or exceeded its request deadline."


class SelectionMode(models.TextChoices):
    DISABLED = "disabled"
    CONTROL = "control"
    SHADOW = "shadow"
    TREATMENT = "treatment"


class PrepareSerializer(serializers.Serializer):
    runtime_version = serializers.CharField(
        max_length=128, required=False, help_text="Cloud agent build version, or unknown."
    )
    run_id = serializers.UUIDField(help_text="Cloud run receiving this human message.")
    message_id = serializers.CharField(max_length=128, help_text="Stable user-message identifier, reused on retries.")
    prompt = serializers.CharField(
        max_length=selection.MAX_PROMPT_CHARS,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Bounded user request text.",
    )
    history = serializers.CharField(
        max_length=selection.MAX_HISTORY_CHARS,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Bounded preceding user and assistant text.",
    )


class PreparedContextSerializer(serializers.Serializer):
    selection_id = serializers.CharField(allow_blank=True, help_text="Selection trace identifier.")
    context = serializers.CharField(allow_blank=True, help_text="Bounded hidden context for a treatment prompt.")  # type: ignore[assignment]
    mode = serializers.ChoiceField(choices=SelectionMode.choices, help_text="Feature flag variant.")
    reason = serializers.CharField(help_text="Selection outcome.")


class ContextSelectionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    scope_object_write_actions = ["prepare"]

    @extend_schema(exclude=True, request=PrepareSerializer, responses={200: PreparedContextSerializer})
    @action(
        detail=False,
        methods=["post"],
        throttle_classes=[ContextSelectionBurstThrottle, ContextSelectionSustainedThrottle],
    )
    def prepare(self, request: Request, **kwargs: object) -> Response:
        serializer = PrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not isinstance(request.user, User):
            raise PermissionDenied("An authenticated actor is required.")
        token = get_oauth_access_token(request)
        bound_task_id = getattr(token, "sandbox_task_id", None)
        if not is_sandbox_oauth_request(request) or not bound_task_id:
            raise PermissionDenied("A task-bound sandbox credential is required.")
        data = dict(serializer.validated_data)
        run_id = data.pop("run_id")
        authorization = get_authorization_header(request).decode("ascii")
        try:
            result = selection.prepare_context_selection(
                self.team_id,
                run_id,
                UUID(str(bound_task_id)),
                request.user,
                selection.SelectionInput(**data),
                authorization,
            )
        except selection.SelectionDenied as error:
            raise PermissionDenied(str(error)) from error
        except selection.SelectionRunNotFound as error:
            raise NotFound() from error
        except selection.SelectionUnavailable as error:
            raise SelectionUnavailable() from error
        return Response(asdict(result))
