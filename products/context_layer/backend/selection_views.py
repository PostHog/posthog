import json
from dataclasses import asdict
from typing import cast
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.oauth_provenance import get_oauth_access_token, is_sandbox_oauth_request
from posthog.permissions import APIScopePermission

from products.context_layer.backend.models import ContextSelectionAttempt
from products.context_layer.backend.selection_service import prepare, selection_mode
from products.context_layer.backend.selection_sources import validate_candidates
from products.context_layer.backend.selection_types import (
    MAX_HISTORY_CHARS,
    MAX_PROMPT_CHARS,
    Candidate,
    SelectionInput,
)
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
    baseline = serializers.CharField(
        max_length=64, required=False, allow_blank=True, help_text="Digest of the prompt before enrichment."
    )


class ReceiptSerializer(serializers.Serializer):
    adapter_elapsed_ms = serializers.FloatField(
        required=False, min_value=0, help_text="Observed adapter call duration; absent before dispatch."
    )
    usage = serializers.JSONField(required=False, allow_null=True, help_text="Adapter-reported usage, when available.")
    prompt = serializers.JSONField(
        help_text="Exact ACP blocks or native Pi context messages submitted to the runtime; limited to 256 KiB."
    )

    def validate_prompt(self, value: object) -> object:
        if len(json.dumps(value).encode()) > 262_144:
            raise serializers.ValidationError("Prompt is too large to archive.")
        return value

    run_id = serializers.UUIDField(help_text="Cloud run receiving this human message.")
    selection_id = serializers.UUIDField(help_text="Selection record returned by prepare.")
    delivery_id = serializers.UUIDField(help_text="Unique adapter dispatch attempt, reused for receipt retries.")
    status = serializers.ChoiceField(
        choices=["dispatching", "completed", "failed"],
        help_text="Observed adapter outcome; dispatching does not prove acceptance.",
    )
    context_included = serializers.BooleanField(
        help_text="Whether the submitted prompt contained the prepared context."
    )
    prompt_hash = serializers.CharField(max_length=64, help_text="SHA-256 of the exact submitted prompt blocks.")
    trace_id = serializers.CharField(
        max_length=128, required=False, allow_blank=True, help_text="Actual response trace, if known."
    )
    stop_reason = serializers.CharField(
        max_length=128, required=False, allow_blank=True, help_text="Adapter stop reason, if known."
    )


class ContextSelectionViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    scope_object_write_actions = ["prepare", "receipt"]

    def _run(self, request: Request, run_id: UUID, *, allow_terminal: bool = False) -> TaskRun:
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
        if not is_current_task_run_actor(run, request.user):
            raise PermissionDenied("The credential no longer belongs to the current actor.")
        if (
            not allow_terminal and run.status != TaskRun.Status.IN_PROGRESS
        ) or run.environment != TaskRun.Environment.CLOUD:
            raise PermissionDenied("The cloud run is not active.")
        return run

    @extend_schema(exclude=True, request=PrepareSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def prepare(self, request: Request, **kwargs) -> Response:
        serializer = PrepareSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = self._run(request, data.pop("run_id"))
        scopes = set((getattr(get_oauth_access_token(request), "scope", "") or "").split())
        result = prepare(run, cast(User, request.user), SelectionInput(**data), scopes)
        return Response(asdict(result))

    @extend_schema(exclude=True, request=ReceiptSerializer, responses={200: OpenApiTypes.OBJECT})
    @action(detail=False, methods=["post"])
    def receipt(self, request: Request, **kwargs) -> Response:
        serializer = ReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        run = self._run(request, data["run_id"], allow_terminal=data["status"] in ("completed", "failed"))

        with transaction.atomic():
            attempt = get_object_or_404(
                ContextSelectionAttempt.objects.select_for_update(),
                id=data["selection_id"],
                run=run,
                actor=request.user,
            )
            if data["context_included"] and (attempt.mode != "treatment" or not attempt.context):
                raise ValidationError("This selection supplied no treatment context.")
            if data["status"] == "dispatching" and data["context_included"]:
                if selection_mode(run, cast(User, request.user)) == "disabled":
                    raise PermissionDenied("Context selection is disabled.")
                scopes = set((getattr(get_oauth_access_token(request), "scope", "") or "").split())
                source_scope = {
                    "skill": "llm_skill:read",
                    "metric": "data_catalog:read",
                    "certification": "data_catalog:read",
                    "relationship": "data_catalog:read",
                    "business_knowledge": "business_knowledge:read",
                }
                selected = set(attempt.evidence.get("selected_ids", []))
                candidates = [
                    Candidate(**c)
                    for c in attempt.evidence.get("retrieval", {}).get("candidates", [])
                    if c["id"] in selected
                ]
                if any(source_scope[c.kind] not in scopes for c in candidates):
                    raise PermissionDenied("A selected source scope is no longer available.")
                current = {
                    c.id: c.as_json() for c in validate_candidates(run.team, cast(User, request.user), candidates)
                }
                if len(candidates) != len(selected) or any(current.get(c.id) != c.as_json() for c in candidates):
                    raise PermissionDenied("A selected source changed or is no longer accessible.")
            receipts = attempt.receipt
            key = str(data["delivery_id"])
            previous = receipts.get(key)
            payload = {k: str(v) if k.endswith("_id") else v for k, v in data.items()}
            if previous and previous["status"] in ("completed", "failed"):
                return Response({"status": "recorded"})
            if len(receipts) >= 20 and not previous:
                raise ValidationError("Too many dispatch attempts.")
            now = timezone.now().isoformat()
            events = list(previous.get("events", [])) if previous else []
            if (
                not previous
                or previous["status"] != payload["status"]
                or previous["prompt_hash"] != payload["prompt_hash"]
            ):
                events.append(
                    {
                        "status": payload["status"],
                        "recorded_at": now,
                        "context_included": payload["context_included"],
                        "prompt_hash": payload["prompt_hash"],
                    }
                )
            receipts[key] = {**payload, "recorded_at": now, "events": events[-20:]}
            attempt.save(update_fields=["receipt"])
        return Response({"status": "recorded"})
