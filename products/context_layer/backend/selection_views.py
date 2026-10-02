from dataclasses import asdict
from typing import cast
from uuid import UUID

from django.shortcuts import get_object_or_404

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request
from posthog.permissions import APIScopePermission

from products.context_layer.backend.selection_execution import bounded_request
from products.context_layer.backend.selection_service import check_deadline, prepare
from products.context_layer.backend.selection_types import MAX_HISTORY_CHARS, MAX_PROMPT_CHARS, SelectionInput
from products.tasks.backend.facade.api import is_current_task_run_actor
from products.tasks.backend.models import TaskRun


class PrepareSerializer(serializers.Serializer):
    runtime_version = serializers.CharField(
        max_length=128, required=False, help_text="Cloud agent build version, or unknown."
    )
    prompt_char_count = serializers.IntegerField(
        min_value=0, required=False, help_text="Original request length before truncation."
    )
    history_source = serializers.ChoiceField(
        choices=["runtime", "resume_prompt"], required=False, help_text="Origin of the bounded conversation context."
    )
    run_id = serializers.UUIDField(help_text="Cloud run receiving this human message.")
    message_id = serializers.CharField(max_length=128, help_text="Stable user-message identifier, reused on retries.")
    prompt = serializers.CharField(
        max_length=MAX_PROMPT_CHARS, allow_blank=True, trim_whitespace=False, help_text="Bounded user request text."
    )
    history = serializers.CharField(
        max_length=MAX_HISTORY_CHARS,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Bounded preceding user and assistant text.",
    )


class PreparedContextSerializer(serializers.Serializer):
    selection_id = serializers.CharField(allow_blank=True, help_text="Selection trace identifier.")
    context = serializers.CharField(allow_blank=True, help_text="Bounded hidden context for a treatment prompt.")  # type: ignore[assignment]
    mode = serializers.ChoiceField(
        choices=["disabled", "control", "shadow", "treatment"], help_text="Feature flag variant."
    )
    reason = serializers.CharField(help_text="Selection outcome.")


class ContextSelectionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    scope_object_write_actions = ["prepare"]

    def _run(self, request: Request, run_id: UUID) -> TaskRun:
        if not isinstance(request.user, User):
            raise PermissionDenied("An authenticated actor is required.")
        token = get_oauth_access_token(request)
        bound_task_id = getattr(token, "sandbox_task_id", None)
        if not is_sandbox_oauth_request(request) or not bound_task_id:
            raise PermissionDenied("A task-bound sandbox credential is required.")
        run = get_object_or_404(
            TaskRun.objects.select_related("task__created_by", "team__organization", "task__team"),
            id=run_id,
            team_id=self.team_id,
            task_id=bound_task_id,
        )
        if not is_current_task_run_actor(run.team_id, run.id, request.user.id):
            raise PermissionDenied("The credential no longer belongs to the current actor.")
        if run.status != TaskRun.Status.IN_PROGRESS or run.environment != TaskRun.Environment.CLOUD:
            raise PermissionDenied("The cloud run is not active.")
        return run

    @extend_schema(exclude=True, request=PrepareSerializer, responses={200: PreparedContextSerializer})
    @action(detail=False, methods=["post"])
    def prepare(self, request: Request, **kwargs: object) -> Response:
        serializer = PrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        def execute(deadline: float) -> Response:
            run = self._run(request, data.pop("run_id"))
            check_deadline(deadline)
            scopes = set((getattr(get_oauth_access_token(request), "scope", "") or "").split())
            result = prepare(run, cast(User, request.user), SelectionInput(**data), scopes)
            check_deadline(deadline)
            if not is_current_task_run_actor(run.team_id, run.id, cast(User, request.user).id):
                raise PermissionDenied("The credential no longer belongs to the current actor.")
            return Response(asdict(result))

        return bounded_request(self.team_id, 3.5, execute)
