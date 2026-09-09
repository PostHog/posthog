from typing import Any
from uuid import UUID

from django.contrib.postgres.expressions import ArraySubquery
from django.db.models import Count, Func, JSONField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce, JSONObject
from django.utils import timezone

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request

from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.presentation.sketchpad.serializers import (
    MAX_PREVIEW_BOXES,
    SketchpadAppendOpsSerializer,
    SketchpadAppendResultSerializer,
    SketchpadCompiledResponseSerializer,
    SketchpadCompileSerializer,
    SketchpadCreateSerializer,
    SketchpadOpsPageSerializer,
    SketchpadOpsQuerySerializer,
    SketchpadSerializer,
    SketchpadSummarySerializer,
    SketchpadWriteSerializer,
)
from products.canvas.backend.presentation.views import CanvasAccessMixin, CanvasStateWriteThrottle
from products.canvas.backend.sketchpad import log as sketchpad_log
from products.canvas.backend.sketchpad.compiler import compiled_fragments
from products.canvas.backend.sketchpad.records import with_sketchpad_records
from products.tasks.backend.facade import api as tasks_facade


class SketchpadAppendOpsThrottle(CanvasStateWriteThrottle):
    scope = "sketchpad_append_ops"
    rate = "600/min"


class SketchpadViewSet(CanvasAccessMixin, viewsets.ModelViewSet):
    scope_object = "canvas"
    queryset = Sketchpad.objects.unscoped().select_related("created_by")
    serializer_class = SketchpadSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    scope_object_read_actions = ["list", "retrieve", "ops", "compiled"]
    scope_object_write_actions = ["create", "partial_update", "destroy", "append_ops"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = super().safely_get_queryset(queryset)
        if self.action in {"ops", "append_ops", "compiled"}:
            queryset = queryset.select_related(None)
        if self.action == "retrieve":
            queryset = with_sketchpad_records(queryset, self.team_id)
        if self.action == "list":
            channel_id = self.request.query_params.get("channel")
            if channel_id:
                try:
                    channel_id = str(UUID(channel_id))
                except ValueError:
                    return queryset.none()
                queryset = queryset.filter(channel_id=channel_id)
            newest = SketchpadOp.objects.for_team(self.team_id).filter(sketchpad_id=OuterRef("pk")).order_by("-seq")
            records = SketchpadRecord.objects.for_team(self.team_id).filter(
                sketchpad_id=OuterRef("pk"), kind="fragment"
            )
            count = records.order_by().values("sketchpad_id").annotate(total=Count("pk")).values("total")
            preview = (
                records.order_by("position", "key")
                .annotate(box=JSONObject(x="value__x", y="value__y", w="value__w", h="value__h"))
                .values("box")[:MAX_PREVIEW_BOXES]
            )
            queryset = queryset.annotate(
                last_actor_user_id=Subquery(newest.values("actor_user_id")[:1]),
                last_actor_kind=Subquery(newest.values("actor_kind")[:1]),
                fragment_count=Coalesce(Subquery(count), 0),
                preview_fragments=Func(ArraySubquery(preview), function="to_jsonb", output_field=JSONField()),
            )
        return queryset.order_by("-updated_at")

    def get_throttles(self) -> list[BaseThrottle]:
        if self.action == "append_ops":
            return [*super().get_throttles(), SketchpadAppendOpsThrottle()]
        return super().get_throttles()

    def get_serializer_class(self) -> type[serializers.BaseSerializer]:
        if self.action == "list":
            return SketchpadSummarySerializer
        return SketchpadSerializer

    @validated_request(
        SketchpadCompileSerializer,
        responses={200: OpenApiResponse(response=SketchpadCompiledResponseSerializer)},
        operation_id="sketchpads_compiled_create",
    )
    @action(methods=["POST"], detail=True)
    def compiled(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        results = compiled_fragments(self.get_object(), request.validated_data["refs"])
        return Response({"results": {ref: artifact.model_dump() for ref, artifact in results.items()}})

    @validated_request(SketchpadCreateSerializer, responses={201: OpenApiResponse(response=SketchpadSerializer)})
    def create(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        channel_id = request.validated_data["channel_id"]
        self._assert_channel_writable(channel_id)
        user = self._request_user()
        sketchpad = Sketchpad.objects.for_team(self.team_id).create(
            team_id=self.team_id,
            channel_id=channel_id,
            name=request.validated_data["name"],
            created_by=user,
        )
        annotated = (
            with_sketchpad_records(Sketchpad.objects.for_team(self.team_id), self.team_id)
            .select_related("created_by")
            .get(pk=sketchpad.pk)
        )
        return Response(SketchpadSerializer(annotated).data, status=status.HTTP_201_CREATED)

    @validated_request(SketchpadWriteSerializer, responses={204: None})
    def partial_update(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        sketchpad = self.get_object()
        data = request.validated_data
        if "channel_id" in data:
            self._assert_channel_writable(data["channel_id"])
        update_fields = _apply_sketchpad_patch(sketchpad, data)
        if update_fields:
            sketchpad.save(update_fields=[*update_fields, "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _assert_channel_writable(self, channel_id: UUID) -> None:
        user = self._request_user()
        if not tasks_facade.channel_exists(self.team_id, channel_id, user.id if user else None):
            raise ValidationError("Channel not found in this team.")
        self._validate_sandbox_channel(channel_id, self._sandbox_task_id(self.request))

    def perform_destroy(self, instance: Sketchpad) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])

    @validated_request(
        query_serializer=SketchpadOpsQuerySerializer,
        responses={200: OpenApiResponse(response=SketchpadOpsPageSerializer)},
        operation_id="sketchpads_ops_retrieve",
    )
    @action(methods=["GET"], detail=True)
    def ops(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        sketchpad = self.get_object()
        since = request.validated_query_data["since"]
        limit = request.validated_query_data["limit"]
        rows = list(
            SketchpadOp.objects.for_team(self.team_id)
            .filter(sketchpad=sketchpad, seq__gt=since, seq__lte=sketchpad.head_seq)
            .select_related("actor_user")
            .order_by("seq")[:limit]
        )
        return Response(SketchpadOpsPageSerializer(instance={"results": rows, "head_seq": sketchpad.head_seq}).data)

    @validated_request(
        SketchpadAppendOpsSerializer,
        responses={
            200: OpenApiResponse(response=SketchpadAppendResultSerializer),
            400: OpenApiResponse(
                description="An op is not a JSON object, has an unknown type, or is over the size cap."
            ),
        },
        operation_id="sketchpads_ops_append",
    )
    @ops.mapping.post
    def append_ops(self, request: ValidatedRequest, *args: Any, **kwargs: Any) -> Response:
        sketchpad = self.get_object()
        data = request.validated_data
        result = sketchpad_log.append_ops(
            sketchpad,
            data["ops"],
            data["actor"]["kind"],
            data["actor"].get("task_id"),
            self._request_user(),
        )
        return Response(SketchpadAppendResultSerializer(instance=result).data)


def _apply_sketchpad_patch(sketchpad: Sketchpad, data: dict[str, Any]) -> list[str]:
    update_fields: list[str] = []
    if "name" in data:
        sketchpad.name = data["name"]
        update_fields.append("name")
    if "channel_id" in data:
        channel_id = data["channel_id"]
        if channel_id != sketchpad.channel_id and sketchpad.pinned_at is not None:
            sketchpad.pinned_at = None
            update_fields.append("pinned_at")
        sketchpad.channel_id = channel_id
        update_fields.append("channel_id")
    if "pinned" in data:
        sketchpad.pinned_at = timezone.now() if data["pinned"] else None
        update_fields.append("pinned_at")
    return update_fields
