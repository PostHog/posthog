from copy import copy
from functools import partial
from typing import Any, cast
from uuid import UUID

from django.contrib.auth import get_user
from django.contrib.auth.models import AnonymousUser
from django.contrib.postgres.expressions import ArraySubquery
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Count, Func, JSONField, OuterRef, QuerySet, Subquery
from django.db.models.functions import Coalesce, JSONObject
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.streaming import sse_streaming_response
from posthog.renderers import ServerSentEventRenderer
from posthog.sync import database_sync_to_async

from products.canvas.backend.models import Sketchpad, SketchpadOp, SketchpadRecord
from products.canvas.backend.presentation.sketchpad.serializers import (
    MAX_PREVIEW_BOXES,
    SketchpadAppendOpsSerializer,
    SketchpadAppendResultSerializer,
    SketchpadCompiledResponseSerializer,
    SketchpadCompileSerializer,
    SketchpadCreateSerializer,
    SketchpadHydratedLogEntrySerializer,
    SketchpadOpsPageSerializer,
    SketchpadOpsQuerySerializer,
    SketchpadPresenceSerializer,
    SketchpadSerializer,
    SketchpadSummarySerializer,
    SketchpadWriteSerializer,
    sketchpad_actor_person,
)
from products.canvas.backend.presentation.views import CanvasAccessMixin, CanvasStateWriteThrottle
from products.canvas.backend.sketchpad import (
    log as sketchpad_log,
    presence as sketchpad_presence,
    stream as sketchpad_stream,
)
from products.canvas.backend.sketchpad.compiler import compiled_fragments
from products.canvas.backend.sketchpad.records import with_sketchpad_records
from products.tasks.backend.facade import api as tasks_facade


class SketchpadPresenceThrottle(CanvasStateWriteThrottle):
    scope = "sketchpad_presence"
    rate = "20/sec"


class SketchpadAppendOpsThrottle(CanvasStateWriteThrottle):
    scope = "sketchpad_append_ops"
    rate = "600/min"


class SketchpadViewSet(CanvasAccessMixin, viewsets.ModelViewSet):
    scope_object = "canvas"
    queryset = Sketchpad.objects.unscoped().select_related("created_by")
    serializer_class = SketchpadSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    scope_object_read_actions = ["list", "retrieve", "ops", "stream", "compiled"]
    scope_object_write_actions = ["create", "partial_update", "destroy", "append_ops", "presence"]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = super().safely_get_queryset(queryset)
        if self.action in {"ops", "append_ops", "presence", "stream", "compiled"}:
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
        if self.action == "presence":
            return [*super().get_throttles(), SketchpadPresenceThrottle()]
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
        return Response(
            SketchpadOpsPageSerializer(
                instance={
                    "results": rows,
                    "head_seq": sketchpad.head_seq,
                    "history_start_seq": sketchpad.history_start_seq,
                    "history_snapshot": sketchpad.history_snapshot,
                }
            ).data
        )

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
            self._actor_task_id(request, data["actor"].get("task_id")),
            self._request_user(),
            base_seq=data["base_seq"],
        )
        events = cast(
            list[dict[str, Any]], SketchpadHydratedLogEntrySerializer(instance=result.appended, many=True).data
        )
        transaction.on_commit(partial(sketchpad_stream.publish_ops, sketchpad.team_id, str(sketchpad.pk), events))
        return Response(SketchpadAppendResultSerializer(instance=result).data)

    def _actor_task_id(self, request: Request, claimed_task_id: UUID | None) -> UUID | None:
        if self._is_sandbox_authenticated(request):
            bound_task_id = self._sandbox_task_id(request)
            if bound_task_id is None or claimed_task_id not in (None, bound_task_id):
                raise PermissionDenied("The acting task must match the sandbox's task.")
            return bound_task_id
        if claimed_task_id is not None:
            user = self._request_user()
            if user is None or not tasks_facade.task_accessible_for_run_view(
                claimed_task_id, self.team_id, user.id, for_control=True
            ):
                raise PermissionDenied("You cannot act for this task.")
        return claimed_task_id

    @extend_schema(
        request=SketchpadPresenceSerializer,
        responses={
            204: OpenApiResponse(description="The ping was broadcast."),
            403: OpenApiResponse(description="Presence names a person, so a user-less credential cannot send it."),
        },
        operation_id="sketchpads_presence_create",
    )
    @action(methods=["POST"], detail=True, required_scopes=["canvas:write"])
    def presence(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        payload = SketchpadPresenceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        sketchpad = self.get_object()
        user = self._request_user()
        if user is None:
            return Response(
                {"detail": "Presence names a person; sign in to send it."}, status=status.HTTP_403_FORBIDDEN
            )
        data = payload.validated_data
        sketchpad_presence.publish_presence(
            sketchpad.team_id,
            str(sketchpad.id),
            sketchpad_presence.SketchpadPresencePing(
                client_id=data["client_id"],
                actor=sketchpad_actor_person(user),
                cursor=data.get("cursor"),
                viewport=data.get("viewport"),
                selected_ids=data["selected_ids"],
                carets=data["carets"],
            ),
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=None,
        responses={(200, "text/event-stream"): OpenApiTypes.STR},
        operation_id="sketchpads_stream_retrieve",
        parameters=[
            OpenApiParameter(
                name="Last-Event-ID",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=False,
                description="Resume after this op. When the stream no longer holds it, "
                "a reload event names the seq to page ops/ from.",
            )
        ],
    )
    @action(
        methods=["GET"],
        detail=True,
        renderer_classes=[ServerSentEventRenderer],
        required_scopes=["canvas:read"],
    )
    def stream(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse | HttpResponse:
        sketchpad = self.get_object()
        team_id = sketchpad.team_id
        sketchpad_id = str(sketchpad.id)
        last_event_id = request.headers.get("Last-Event-ID")
        can_read = database_sync_to_async(self._can_read_stream)
        user = self._request_user()

        return sse_streaming_response(
            partial(
                sketchpad_stream.stream_sketchpad_sse,
                team_id,
                sketchpad_id,
                can_read=can_read,
                last_event_id=last_event_id,
            ),
            endpoint="sketchpad_stream",
            principal=f"user:{user.pk}" if user else f"team:{team_id}",
        )

    def _can_read_stream(self) -> bool:
        raw_request = copy(self.request._request)
        if hasattr(raw_request, "session"):
            raw_request.session = type(raw_request.session)(session_key=raw_request.session.session_key)
            raw_request.user = get_user(raw_request)
        else:
            raw_request.user = AnonymousUser()
        view = type(self)(basename=self.basename, detail=True, required_scopes=["canvas:read"])
        view.action_map = {"get": "stream"}
        view.args, view.kwargs = self.args, self.kwargs.copy()
        view.format_kwarg = None
        view.request = view.initialize_request(raw_request, *view.args, **view.kwargs)
        try:
            view.perform_authentication(view.request)
            view.check_permissions(view.request)
            view.get_object()
        except (APIException, Http404, ObjectDoesNotExist):
            return False
        return True


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
