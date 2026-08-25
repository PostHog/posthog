import json
from typing import Any, cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, SimpleRateThrottle

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.event_usage import report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, log_activity
from posthog.models.user import User
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.canvas.backend import build_service, error_reports
from products.canvas.backend.actions import CANVAS_ACTIONS, canvas_actions_disabled
from products.canvas.backend.capabilities import declared_actions, declared_state_scopes
from products.canvas.backend.contract import contract_limits
from products.canvas.backend.facade.api import (
    apply_layout_ops,
    default_layout,
    seed_home_canvas,
    subtract_preexisting_diagnostics,
    validate_layout,
    validate_layout_references,
)
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasHomePreference, CanvasSourceVersion, CanvasState
from products.canvas.backend.presentation.serializers import (
    CanvasActionInvokeSerializer,
    CanvasActionResultSerializer,
    CanvasActionsResponseSerializer,
    CanvasAgentRequestResultSerializer,
    CanvasAgentRequestSerializer,
    CanvasBuildActionSerializer,
    CanvasBuildSerializer,
    CanvasBuildsResponseSerializer,
    CanvasCapabilityWideningSerializer,
    CanvasCreateSerializer,
    CanvasDraftSerializer,
    CanvasErrorReportResultSerializer,
    CanvasFixRequestResultSerializer,
    CanvasLayoutPatchSerializer,
    CanvasLayoutPublishResponseSerializer,
    CanvasLayoutPublishSerializer,
    CanvasLayoutResponseSerializer,
    CanvasPromoteSerializer,
    CanvasPublishConflictSerializer,
    CanvasPublishCurrentVersionSerializer,
    CanvasReportErrorSerializer,
    CanvasRequestFixSerializer,
    CanvasRevertSerializer,
    CanvasSerializer,
    CanvasSourceDraftResponseSerializer,
    CanvasSourceDraftSerializer,
    CanvasSourceEditSerializer,
    CanvasSourceInvalidSerializer,
    CanvasSourcePublishResponseSerializer,
    CanvasSourcePublishSerializer,
    CanvasSourceResponseSerializer,
    CanvasStateEntrySerializer,
    CanvasStateResponseSerializer,
    CanvasStateSetSerializer,
    CanvasSummarySerializer,
    CanvasUpdateSerializer,
    CanvasValidateRequestSerializer,
    CanvasValidateResponseSerializer,
    CanvasVersionSerializer,
    canvas_url,
)
from products.canvas.backend.source import apply_source_edits, has_errors, validate_source_project
from products.tasks.backend.facade import api as tasks_facade

logger = structlog.get_logger(__name__)

# The canvas's build lifecycle returns this many recent builds (the published
# build is unioned in even when it has aged past the window).
BUILDS_WINDOW = 20
# Version-history window for the client's undo/revert browser.
VERSIONS_WINDOW = 100
# Write-time bounds on canvas runtime state (ph.state), from the platform
# contract so the desktop bridge mirrors them instead of restating numbers.
# They keep every access a point lookup and cap table growth by canvas count.
CANVAS_STATE_MAX_VALUE_BYTES = contract_limits()["maxStateValueBytes"]
CANVAS_STATE_MAX_KEYS_PER_SCOPE = contract_limits()["maxStateKeysPerScope"]


def _capacity_response() -> Response:
    return Response(
        {"detail": "Canvas build capacity is temporarily exhausted. Try again shortly."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def _conflict_response(error: build_service.CanvasVersionConflict) -> Response:
    return Response(
        {
            "detail": "The canvas changed since it was read (a concurrent publish or a revert). "
            "Re-fetch the canvas source, re-apply the edits, and publish again.",
            "code": "version_conflict",
            "current_version_id": error.current_version_id,
        },
        status=status.HTTP_409_CONFLICT,
    )


def _invalid_response(diagnostics: list[dict[str, Any]]) -> Response:
    return Response(
        {
            "detail": "The source project failed validation; fix the error diagnostics and publish again.",
            "code": "invalid_source_project",
            "diagnostics": diagnostics,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _state_rejection() -> Response:
    return Response(
        {"detail": "Canvas state is a viewer surface; sandbox tokens cannot use it."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _grid_rejection(canvas: Canvas) -> Response | None:
    """Reject file-source reads/writes on a grid canvas, whose source is a layout document."""
    if canvas.kind != Canvas.KIND_GRID:
        return None
    return _wrong_kind_response(
        "Grid canvases are compositions of components; use the layout endpoints, not file source."
    )


def _layout_diagnostics(team_id: int, user_id: int | None, layout: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics = validate_layout(layout)
    if has_errors(diagnostics):
        return diagnostics
    return [*diagnostics, *validate_layout_references(team_id, user_id, layout)]


def _non_grid_rejection(canvas: Canvas) -> Response | None:
    """Reject layout reads/writes on canvases whose source is a file project."""
    if canvas.kind == Canvas.KIND_GRID:
        return None
    return _wrong_kind_response(
        "Only grid canvases have a layout; freeform and component canvases publish source projects."
    )


def _wrong_kind_response(detail: str) -> Response:
    return Response({"detail": detail, "code": "wrong_canvas_kind"}, status=status.HTTP_400_BAD_REQUEST)


class CanvasStateWriteThrottle(SimpleRateThrottle):
    """Per viewer per canvas. State writes are interaction-driven app data, so
    the ceiling is generous — it exists to stop a canvas render loop from
    hammering the table, not to meter normal use."""

    scope = "canvas_state_write"
    rate = "240/min"

    def get_cache_key(self, request: Request, view: Any) -> str:
        ident = request.user.pk if request.user and request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": f"{ident}:{view.kwargs.get('pk')}"}


class CanvasActionInvokeThrottle(CanvasStateWriteThrottle):
    """Tighter than state writes: every invocation is a real PostHog write."""

    scope = "canvas_action_invoke"
    rate = "60/min"


class CanvasViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Canvases: agent-built sandboxed browser apps, filed into channels.

    Source is versioned per publish and built server-side; the canvas app
    renders the published build's artifact from the isolated artifact origin.
    """

    scope_object = "canvas"
    # unscoped() because a class attribute is built before any team context
    # exists; safely_get_queryset applies the team filter explicitly.
    # current_source_version feeds the component_meta field on every row.
    queryset = Canvas.objects.unscoped().select_related("created_by", "current_source_version")
    serializer_class = CanvasSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    scope_object_read_actions = [
        "list",
        "retrieve",
        "source",
        "versions",
        "drafts",
        "builds",
        "validate",
        "state",
        "layout",
    ]
    scope_object_write_actions = [
        "create",
        "partial_update",
        "destroy",
        "publish",
        "publish_current_version",
        "edit",
        "draft",
        "promote",
        "revert",
        "build_action",
        "report_error",
        "request_fix",
        "set_state",
        "invoke_action",
        "request_agent",
        "publish_layout",
        "patch_layout",
        "home",
    ]

    def get_throttles(self) -> list[BaseThrottle]:
        # On top of the defaults, not instead of them: the per-canvas key must
        # not let a caller rotate canvases past the project-wide limits.
        if self.action == "set_state":
            return [*super().get_throttles(), CanvasStateWriteThrottle()]
        if self.action == "invoke_action":
            return [*super().get_throttles(), CanvasActionInvokeThrottle()]
        return super().get_throttles()

    def dangerously_get_required_scopes(self, request: Request, view: Any) -> list[str] | None:
        # Invoking a verb writes the target resource, so a scoped credential
        # must hold that resource's scope — canvas:write alone is not consent
        # to create tasks or annotations.
        if getattr(view, "action", None) != "invoke_action":
            return None
        verb = request.data.get("verb") if isinstance(request.data, dict) else None
        entry = CANVAS_ACTIONS.get(verb) if isinstance(verb, str) else None
        if entry is None:
            return None
        return ["canvas:write", *entry.required_scopes]

    _CREATOR_ONLY_ACTIONS = {
        "partial_update",
        "destroy",
        "publish",
        "edit",
        "draft",
        "promote",
        "revert",
        "build_action",
        "publish_layout",
        "patch_layout",
    }

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "channel", OpenApiTypes.UUID, required=False, description="Only return canvases in this channel."
            ),
            OpenApiParameter(
                "kind",
                OpenApiTypes.STR,
                required=False,
                enum=Canvas.KINDS,
                description="Only return canvases of this kind. kind=component lists the component store.",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                required=False,
                description="Only return canvases whose name or description contains this text (case-insensitive).",
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team_id=self.team_id, deleted=False)
        user = self._request_user()
        is_sandbox_authenticated = self._is_sandbox_authenticated(self.request)
        if is_sandbox_authenticated:
            sandbox_task_id = self._sandbox_task_id(self.request)
            if sandbox_task_id is None:
                return queryset.none()
            public_canvas_q = tasks_facade.visible_channels_q(None, relation="channel")
            if user is None:
                queryset = (
                    queryset.filter(public_canvas_q)
                    if self.action in self.scope_object_read_actions
                    else queryset.none()
                )
            else:
                actor_canvas_q = Q(created_by_id=user.id) & tasks_facade.visible_channels_q(user.id, relation="channel")
                can_use_visible_canvas = self.action in [*self.scope_object_read_actions, "set_state"]
                queryset = queryset.filter(
                    public_canvas_q | actor_canvas_q if can_use_visible_canvas else actor_canvas_q
                )
        else:
            # Channels are per-user for the personal kind: the facade's visibility
            # rule makes a canvas filed into someone else's personal channel
            # invisible (and unwritable) to everyone but its owner.
            queryset = queryset.filter(tasks_facade.visible_channels_q(user.id if user else None, relation="channel"))
        if not is_sandbox_authenticated and self.action in self._CREATOR_ONLY_ACTIONS:
            if user is None:
                return queryset.none()
            queryset = queryset.filter(created_by_id=user.id)
        if self.action == "list":
            channel_id = self.request.query_params.get("channel")
            if channel_id:
                try:
                    channel_id = str(UUID(channel_id))
                except ValueError:
                    return queryset.none()
                queryset = queryset.filter(channel_id=channel_id)
            kind = self.request.query_params.get("kind")
            if kind:
                if kind not in Canvas.KINDS:
                    return queryset.none()
                queryset = queryset.filter(kind=kind)
            search = self.request.query_params.get("search")
            if search:
                queryset = queryset.filter(Q(name__icontains=search) | Q(description__icontains=search))
        return queryset.order_by("-created_at")

    @extend_schema(
        operation_id="canvases_create",
        request=CanvasCreateSerializer,
        responses={
            201: CanvasSerializer,
            403: OpenApiResponse(description="The sandbox token is not bound to this task or space."),
        },
    )
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Create a new, empty canvas in a channel; give it source by publishing a project."""
        payload = CanvasCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        channel_id = payload.validated_data["channel_id"]
        user = self._request_user()
        # The facade's visibility rule, not a bare team filter: filing into
        # someone else's personal channel must be refused here too.
        if not tasks_facade.channel_exists(self.team_id, channel_id, user.id if user else None):
            return Response({"detail": "Channel not found in this team."}, status=status.HTTP_400_BAD_REQUEST)
        sandbox_task_id = self._sandbox_task_id(request)
        if self._is_sandbox_authenticated(request):
            task_channel_id = tasks_facade.task_channel_id(sandbox_task_id, self.team_id) if sandbox_task_id else None
            if task_channel_id != channel_id:
                # Naming the right channel lets the agent recover in one step
                # and tell the user where the canvas will actually land.
                hint = f' Use the task\'s channel "{task_channel_id}".' if task_channel_id else ""
                return Response(
                    {"detail": f"This sandbox can create canvases only in its task's space.{hint}"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        canvas = Canvas.objects.create(
            team_id=self.team_id,
            channel_id=channel_id,
            name=payload.validated_data["name"],
            kind=payload.validated_data["kind"],
            description=payload.validated_data["description"],
            template_id=payload.validated_data["template_id"],
            created_by=user,
            # A sandbox-created canvas is its task's deliverable: bind
            # the two at birth so the client can show the run on the
            # canvas and nest the task under it — composer-initiated
            # generations have no client-side create to record it.
            generation_task_id=sandbox_task_id,
        )
        self._log_canvas_activity(canvas, "created", Detail(name=canvas.name))
        self._report_canvas_action(
            "canvas created",
            canvas,
            kind=canvas.kind,
            template_id=canvas.template_id,
            is_sandbox_created=canvas.generation_task_id is not None,
        )
        return Response(CanvasSerializer(canvas).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="canvases_partial_update",
        request=CanvasUpdateSerializer,
        responses={200: CanvasSerializer},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update canvas metadata, including the space it belongs to."""
        canvas = self.get_object()
        payload = CanvasUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        update_fields = ["updated_at"]
        changes: list[Change] = []

        def record(field: str, before: Any = None, after: Any = None) -> None:
            changes.append(Change(type="Canvas", action="changed", field=field, before=before, after=after))

        if "name" in data:
            if data["name"] != canvas.name:
                record("name", canvas.name, data["name"])
            canvas.name = data["name"]
            update_fields.append("name")
        if "context" in data:
            # The author-context markdown is content, not configuration — record
            # that it changed without copying it into the audit trail.
            if data["context"] != canvas.context:
                record("context")
            canvas.context = data["context"]
            update_fields.append("context")
        if "description" in data:
            if data["description"] != canvas.description:
                record("description", canvas.description, data["description"])
            canvas.description = data["description"]
            update_fields.append("description")
        if "channel_id" in data:
            channel_id = data["channel_id"]
            user = self._request_user()
            if not tasks_facade.channel_exists(self.team_id, channel_id, user.id if user else None):
                return Response({"detail": "Channel not found in this team."}, status=status.HTTP_400_BAD_REQUEST)
            if self._is_sandbox_authenticated(request):
                sandbox_task_id = self._sandbox_task_id(request)
                task_channel_id = (
                    tasks_facade.task_channel_id(sandbox_task_id, self.team_id) if sandbox_task_id else None
                )
                if task_channel_id != channel_id:
                    return Response(
                        {"detail": "This sandbox can file canvases only in its task's space."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            if channel_id != canvas.channel_id:
                record("channel", str(canvas.channel_id), str(channel_id))
                if canvas.pinned_at is not None:
                    record("pinned", True, False)
                    canvas.pinned_at = None
                    update_fields.append("pinned_at")
            canvas.channel_id = channel_id
            update_fields.append("channel_id")
        if "pinned" in data:
            was_pinned = canvas.pinned_at is not None
            if data["pinned"] != was_pinned:
                record("pinned", was_pinned, data["pinned"])
            canvas.pinned_at = timezone.now() if data["pinned"] else None
            update_fields.append("pinned_at")
        if "generation_task_id" in data:
            task_id = data["generation_task_id"]
            user = self._request_user()
            if task_id is not None and (
                user is None or not tasks_facade.task_owned_by_user(task_id, self.team_id, user.id)
            ):
                return Response({"detail": "Task not found in this team."}, status=status.HTTP_400_BAD_REQUEST)
            canvas.generation_task_id = task_id
            update_fields.append("generation_task_id")
        canvas.save(update_fields=update_fields)
        if changes:
            self._log_canvas_activity(canvas, "updated", Detail(name=canvas.name, changes=changes))
        return Response(CanvasSerializer(canvas).data)

    def perform_destroy(self, instance: Canvas) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])
        self._log_canvas_activity(instance, "deleted", Detail(name=instance.name))
        self._report_canvas_action("canvas deleted", instance)

    @extend_schema(
        operation_id="canvases_source_retrieve",
        responses={200: CanvasSourceResponseSerializer},
        request=None,
        parameters=[
            OpenApiParameter(
                name="version_id",
                type=str,
                required=False,
                description="Read this historical source version instead of the head (for version browsing).",
            )
        ],
    )
    @action(methods=["GET"], detail=True)
    def source(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read the canvas's source project and its `current_version_id`.

        Always call this before editing: edit the returned files, then publish
        the complete project passing the returned version id as
        `expected_current_version_id` so concurrent edits are not overwritten.
        `?version_id=` reads a historical version instead of the head.
        """
        canvas = self.get_object()
        rejection = _grid_rejection(canvas)
        if rejection is not None:
            return rejection
        requested_version_id = request.query_params.get("version_id")
        try:
            if requested_version_id:
                version = (
                    CanvasSourceVersion.objects.for_team(self.team_id)
                    .filter(pk=requested_version_id, canvas_id=canvas.id)
                    .first()
                )
                if version is None:
                    return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
                project = build_service.read_source_project(version)
            else:
                project, _ = build_service.current_source_project(canvas)
        except DjangoValidationError:
            return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        except ObjectStorageError:
            return Response(
                {"detail": "The canvas's source is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        response = {
            "canvas": CanvasSummarySerializer(canvas).data,
            "project": project,
            "current_version_id": (str(canvas.current_source_version_id) if canvas.current_source_version_id else None),
        }
        return Response(response)

    @extend_schema(
        operation_id="canvases_versions_retrieve",
        responses={200: CanvasVersionSerializer(many=True)},
        request=None,
    )
    @action(methods=["GET"], detail=True)
    def versions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The canvas's published source-version history, newest first (metadata only).

        Drafts are excluded: they are staged versions that have never been the
        head, so they are not part of the undo/revert timeline. Fetch a draft's
        files with `source?version_id=` to preview it before promoting.
        """
        canvas = self.get_object()
        versions = (
            canvas.source_versions.filter(draft=False)
            .select_related("created_by")
            .order_by("-created_at")[:VERSIONS_WINDOW]
        )
        page = self.paginate_queryset(versions)
        if page is not None:
            return self.get_paginated_response(CanvasVersionSerializer(page, many=True).data)
        return Response(CanvasVersionSerializer(versions, many=True).data)

    @extend_schema(
        operation_id="canvases_validate_create",
        request=CanvasValidateRequestSerializer,
        responses={200: CanvasValidateResponseSerializer},
    )
    @action(methods=["POST"], detail=True)
    def validate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Validate a candidate source project without publishing it. Side-effect free."""
        canvas = self.get_object()
        payload = CanvasValidateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        diagnostics = validate_source_project(payload.validated_data["project"], kind=canvas.kind)
        return Response({"valid": not has_errors(diagnostics), "diagnostics": diagnostics})

    @extend_schema(
        operation_id="canvases_publish_current_version_create",
        request=CanvasPublishCurrentVersionSerializer,
        responses={
            200: CanvasBuildSerializer,
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id.",
            ),
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="publish-current-version")
    def publish_current_version(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Queue a build for the current source version without changing source or metadata."""
        canvas = self.get_object()
        rejection = _grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasPublishCurrentVersionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            canvas, build = build_service.publish_current_source_version(
                canvas,
                payload.validated_data["expected_current_version_id"],
                user=self._request_user(),
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        self._report_canvas_action(
            "canvas published",
            canvas,
            version_id=str(build.source_version_id),
            first_publish=False,
            is_sandbox_publish=self._sandbox_task_id(request) is not None,
        )
        return Response(CanvasBuildSerializer(build).data)

    @extend_schema(
        operation_id="canvases_publish_create",
        request=CanvasSourcePublishSerializer,
        responses={
            200: CanvasSourcePublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="The source project failed validation.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id (a concurrent publish or a revert).",
            ),
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True)
    def publish(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish a complete source project as the canvas's new head version.

        Validation errors reject the publish (400) and leave the canvas
        untouched; a stale `expected_current_version_id` is rejected with 409.
        A successful publish queues a server-side build.
        """
        canvas = self.get_object()
        rejection = _grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasSourcePublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._publish(
            request,
            canvas,
            project=payload.validated_data["project"],
            prompt=payload.validated_data.get("prompt"),
            name=payload.validated_data.get("name"),
            has_expected_version="expected_current_version_id" in payload.validated_data,
            expected_version_id=payload.validated_data.get("expected_current_version_id"),
        )

    @extend_schema(
        operation_id="canvases_edit_create",
        request=CanvasSourceEditSerializer,
        responses={
            200: CanvasSourcePublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="An edit targeted a missing file, or the edited project failed validation.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id (a concurrent publish or a revert).",
            ),
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True)
    def edit(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish per-file edits against the canvas's current source project.

        Diff-aware alternative to sending the complete project: each operation
        sets a file's content or (content null) deletes it, applied to the head
        the caller read. `expected_current_version_id` is mandatory here —
        relative edits against an unverified base could silently merge into
        someone else's newer work.
        """
        canvas = self.get_object()
        rejection = _grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasSourceEditSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            project, _ = build_service.current_source_project(canvas)
        except ObjectStorageError:
            return Response(
                {"detail": "The canvas's source is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        project, diagnostics = apply_source_edits(project, payload.validated_data["operations"])
        if diagnostics:
            return Response(
                {
                    "detail": "The edit could not be applied to the canvas's current source.",
                    "code": "invalid_source_project",
                    "diagnostics": diagnostics,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self._publish(
            request,
            canvas,
            project=project,
            prompt=payload.validated_data.get("prompt"),
            name=payload.validated_data.get("name"),
            has_expected_version=True,
            expected_version_id=payload.validated_data["expected_current_version_id"],
        )

    def _publish(
        self,
        request: Request,
        canvas: Canvas,
        *,
        project: dict[str, Any],
        prompt: str | None,
        name: str | None,
        has_expected_version: bool,
        expected_version_id: str | None,
    ) -> Response:
        diagnostics = validate_source_project(project, kind=canvas.kind)
        if has_errors(diagnostics):
            return _invalid_response(diagnostics)

        user = self._request_user()
        task_id = self._sandbox_task_id(request)
        try:
            canvas, version, _build, first_publish = build_service.publish_source_project(
                canvas,
                project=project,
                prompt=prompt,
                name=name,
                has_expected_version=has_expected_version,
                expected_version_id=expected_version_id,
                task_id=task_id,
                created_by=user,
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except ObjectStorageError:
            return Response(
                {"detail": "Canvas source storage is temporarily unavailable; the publish was not saved."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if first_publish:
            self._announce_canvas_created(task_id, user, canvas)

        posthog_capabilities = (version.capabilities or {}).get("posthog") or {}
        self._report_canvas_action(
            "canvas published",
            canvas,
            version_id=str(version.id),
            first_publish=first_publish,
            file_count=len(project.get("files") or {}),
            source_size_bytes=version.source_size,
            insight_capability_count=len(posthog_capabilities.get("insights") or []),
            capture_event_capability_count=len(posthog_capabilities.get("captureEvents") or []),
            inline_queries_capability=bool(posthog_capabilities.get("inlineQueries")),
            agent_requests_capability=bool(posthog_capabilities.get("agentRequests")),
            is_sandbox_publish=task_id is not None,
        )

        return Response(
            {
                "canvas": CanvasSummarySerializer(canvas).data,
                "current_version_id": str(version.id),
                "diagnostics": diagnostics,
            }
        )

    @extend_schema(
        operation_id="canvases_drafts_retrieve",
        responses={200: CanvasDraftSerializer(many=True)},
        request=None,
    )
    @action(methods=["GET"], detail=True)
    def drafts(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The canvas's staged draft versions, newest first, each with its latest build status.

        A draft is a version that was built but never made the head. Preview one
        with `source?version_id=`, then make it live with `promote`.
        """
        canvas = self.get_object()
        draft_versions = list(
            canvas.source_versions.filter(draft=True)
            .select_related("created_by")
            .order_by("-created_at")[:VERSIONS_WINDOW]
        )
        # Newest build per draft version. Only the id/status/version are needed,
        # so skip the heavy manifest/diagnostics JSON columns.
        latest_build_by_version: dict[Any, CanvasBuild] = {}
        for build in (
            canvas.builds.filter(source_version_id__in=[version.id for version in draft_versions])
            .only("id", "source_version_id", "status")
            .order_by("source_version_id", "-created_at")
        ):
            latest_build_by_version.setdefault(build.source_version_id, build)
        data = []
        for version in draft_versions:
            build = latest_build_by_version.get(version.id)
            data.append(
                {
                    "version_id": str(version.id),
                    "prompt": version.prompt,
                    "created_by": version.created_by,
                    "created_at": version.created_at,
                    "build_status": build.status if build else None,
                    "build_id": str(build.id) if build else None,
                }
            )
        return Response(CanvasDraftSerializer(data, many=True).data)

    @extend_schema(
        operation_id="canvases_draft_create",
        request=CanvasSourceDraftSerializer,
        responses={
            200: CanvasSourceDraftResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="The source project failed validation.",
            ),
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True)
    def draft(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Stage a complete source project as a draft version and build it, without publishing.

        The draft gets the same validation, versioning, and server-side build as
        a publish, but the canvas's head and live build never move, so nothing
        changes for viewers. Promote the version with `promote` to make it live.
        The response reports how the draft's declared capabilities widen the
        current head's, so growth in access can be reviewed before it ships.
        No version guard applies: a draft conflicts with nothing.
        """
        canvas = self.get_object()
        rejection = _grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasSourceDraftSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        project = payload.validated_data["project"]
        diagnostics = validate_source_project(project, kind=canvas.kind)
        if has_errors(diagnostics):
            return _invalid_response(diagnostics)
        task_id = self._sandbox_task_id(request)
        try:
            version, build, widening = build_service.create_draft_version(
                canvas,
                project=project,
                prompt=payload.validated_data.get("prompt"),
                task_id=task_id,
                created_by=self._request_user(),
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except ObjectStorageError:
            return Response(
                {"detail": "Canvas source storage is temporarily unavailable; the draft was not saved."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        self._report_canvas_action(
            "canvas draft created",
            canvas,
            version_id=str(version.id),
            widens_capabilities=widening.widens,
            is_sandbox_draft=task_id is not None,
        )
        return Response(
            {
                "version_id": str(version.id),
                "build": CanvasBuildSerializer(build).data,
                "diagnostics": diagnostics,
                "capability_widening": CanvasCapabilityWideningSerializer(widening).data,
            }
        )

    @extend_schema(
        operation_id="canvases_promote_create",
        request=CanvasPromoteSerializer,
        responses={
            200: CanvasBuildSerializer,
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id (a concurrent publish or a revert).",
            ),
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True)
    def promote(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Make a draft version the canvas's live head.

        A draft whose build is ready goes live immediately, with no rebuild;
        otherwise a fresh build is queued. Returns that build.
        """
        canvas = self.get_object()
        payload = CanvasPromoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            canvas, build = build_service.promote_draft_version(
                canvas,
                payload.validated_data["version_id"],
                payload.validated_data["expected_current_version_id"],
                user=self._request_user(),
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except CanvasSourceVersion.DoesNotExist:
            return Response({"detail": "Draft version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        self._report_canvas_action(
            "canvas draft promoted",
            canvas,
            version_id=str(payload.validated_data["version_id"]),
            build_reused=build.status == CanvasBuild.STATUS_READY,
        )
        return Response(CanvasBuildSerializer(build).data)

    @extend_schema(
        operation_id="canvases_revert_create",
        request=CanvasRevertSerializer,
        responses={
            200: CanvasBuildSerializer,
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True)
    def revert(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Move the canvas's head back to an existing source version and rebuild it."""
        canvas = self.get_object()
        payload = CanvasRevertSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            canvas, build = build_service.revert_to_version(
                canvas,
                payload.validated_data["version_id"],
                payload.validated_data["expected_current_version_id"],
                user=self._request_user(),
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except CanvasSourceVersion.DoesNotExist:
            return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        self._report_canvas_action("canvas reverted", canvas, version_id=str(payload.validated_data["version_id"]))
        return Response(CanvasBuildSerializer(build).data)

    @extend_schema(
        operation_id="canvases_builds_retrieve",
        responses={200: CanvasBuildsResponseSerializer},
        request=None,
        parameters=[
            OpenApiParameter(
                name="version_id",
                type=OpenApiTypes.UUID,
                required=False,
                description="Include the retained ready build for this historical source version.",
            )
        ],
    )
    @action(methods=["GET"], detail=True)
    def builds(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read the canvas's build lifecycle: live pointers plus recent builds.

        A publish queues a build; poll this until it is ready (the live pointer
        advances) or failed (fix the error diagnostics and publish again — the
        last good build stays live).
        """
        canvas = self.get_object()
        builds = list(canvas.builds.order_by("-created_at")[:BUILDS_WINDOW])
        # The live build must always be visible, even when newer (e.g. failed)
        # builds have pushed it past the window.
        if canvas.published_build_id and all(build.id != canvas.published_build_id for build in builds):
            published = canvas.builds.filter(id=canvas.published_build_id).first()
            if published is not None:
                builds.append(published)
        requested_version_id = request.query_params.get("version_id")
        if requested_version_id:
            try:
                requested_version = canvas.source_versions.filter(id=requested_version_id).first()
            except DjangoValidationError:
                requested_version = None
            if requested_version is None:
                return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
            historical_build = (
                canvas.builds.filter(source_version_id=requested_version.id, status=CanvasBuild.STATUS_READY)
                .order_by("-created_at")
                .first()
            )
            if historical_build is not None and all(build.id != historical_build.id for build in builds):
                builds.append(historical_build)
        response = {
            "published_build_id": str(canvas.published_build_id) if canvas.published_build_id else None,
            "current_version_id": (str(canvas.current_source_version_id) if canvas.current_source_version_id else None),
            "builds": CanvasBuildSerializer(builds, many=True).data,
        }
        return Response(response)

    @extend_schema(
        operation_id="canvases_layout_retrieve",
        responses={
            200: CanvasLayoutResponseSerializer,
            400: OpenApiResponse(description="The canvas is not a grid canvas."),
        },
        request=None,
        parameters=[
            OpenApiParameter(
                name="version_id",
                type=str,
                required=False,
                description="Read this historical layout version instead of the head (for version browsing).",
            )
        ],
    )
    @action(methods=["GET"], detail=True)
    def layout(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read a grid canvas's layout document and its `current_version_id`.

        Always call this before editing: pass the returned version id as
        `expected_current_version_id` on publish/patch so concurrent edits are
        not overwritten. A grid canvas with no versions yet returns the
        default empty layout with a null version id.
        """
        canvas = self.get_object()
        rejection = _non_grid_rejection(canvas)
        if rejection is not None:
            return rejection
        requested_version_id = request.query_params.get("version_id")
        try:
            if requested_version_id:
                version = (
                    CanvasSourceVersion.objects.for_team(self.team_id)
                    .filter(pk=requested_version_id, canvas_id=canvas.id)
                    .first()
                )
                if version is None:
                    return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
                layout = build_service.read_source_project(version)
            else:
                layout = self._read_current_layout(canvas)
        except DjangoValidationError:
            return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        except ObjectStorageError:
            return Response(
                {"detail": "The canvas's layout is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            CanvasLayoutResponseSerializer(
                instance={
                    "canvas": canvas,
                    "layout": layout,
                    "current_version_id": (
                        str(canvas.current_source_version_id) if canvas.current_source_version_id else None
                    ),
                }
            ).data
        )

    @extend_schema(
        operation_id="canvases_layout_publish_create",
        request=CanvasLayoutPublishSerializer,
        responses={
            200: CanvasLayoutPublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="The canvas is not a grid canvas, or the layout failed validation.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id.",
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="layout/publish")
    def publish_layout(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Publish a complete layout document as the grid canvas's new head version.

        Layout is data, not code: the new version is live immediately, with no
        build. Validation errors reject the publish (400) and leave the canvas
        untouched; a stale `expected_current_version_id` is rejected with 409.
        """
        canvas = self.get_object()
        rejection = _non_grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasLayoutPublishSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return self._publish_layout(
            request,
            canvas,
            layout=payload.validated_data["layout"],
            prompt=payload.validated_data.get("prompt"),
            has_expected_version="expected_current_version_id" in payload.validated_data,
            expected_version_id=payload.validated_data.get("expected_current_version_id"),
        )

    @extend_schema(
        operation_id="canvases_layout_patch_create",
        request=CanvasLayoutPatchSerializer,
        responses={
            200: CanvasLayoutPublishResponseSerializer,
            400: OpenApiResponse(
                response=CanvasSourceInvalidSerializer,
                description="An operation targeted a missing placement, or the edited layout failed validation.",
            ),
            409: OpenApiResponse(
                response=CanvasPublishConflictSerializer,
                description="The canvas moved past expected_current_version_id.",
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="layout/patch")
    def patch_layout(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Apply surgical operations to the grid canvas's current layout.

        The default write path for both the editor and agents: add, move,
        resize, fill, or remove one placement without resending the layout.
        `expected_current_version_id` is mandatory so an agent filling a box
        and a user rearranging widgets cannot overwrite each other.
        """
        canvas = self.get_object()
        rejection = _non_grid_rejection(canvas)
        if rejection is not None:
            return rejection
        payload = CanvasLayoutPatchSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            current = self._read_current_layout(canvas)
        except ObjectStorageError:
            return Response(
                {"detail": "The canvas's layout is temporarily unavailable."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        layout, diagnostics = apply_layout_ops(current, payload.validated_data["operations"])
        if diagnostics:
            return Response(
                {
                    "detail": "The operations could not be applied to the canvas's current layout.",
                    "code": "invalid_layout",
                    "diagnostics": diagnostics,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._publish_layout(
            request,
            canvas,
            layout=layout,
            prompt=payload.validated_data.get("prompt"),
            has_expected_version=True,
            expected_version_id=payload.validated_data["expected_current_version_id"],
            baseline_layout=current,
        )

    def _publish_layout(
        self,
        request: Request,
        canvas: Canvas,
        *,
        layout: dict[str, Any],
        prompt: str | None,
        has_expected_version: bool,
        expected_version_id: str | None,
        baseline_layout: dict[str, Any] | None = None,
    ) -> Response:
        acting_user = self._request_user()
        acting_user_id = acting_user.id if acting_user else None
        diagnostics = _layout_diagnostics(self.team_id, acting_user_id, layout)
        # Patches (which pass their baseline) answer only for the problems they
        # introduce; publishes replace the whole document and stay strict.
        if baseline_layout is not None and has_errors(diagnostics):
            diagnostics = subtract_preexisting_diagnostics(
                diagnostics, _layout_diagnostics(self.team_id, acting_user_id, baseline_layout)
            )
        if has_errors(diagnostics):
            return Response(
                {
                    "detail": "The layout failed validation; fix the error diagnostics and publish again.",
                    "code": "invalid_layout",
                    "diagnostics": diagnostics,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = self._request_user()
        task_id = self._sandbox_task_id(request)
        try:
            canvas, version = build_service.publish_grid_layout(
                canvas,
                layout=layout,
                prompt=prompt,
                has_expected_version=has_expected_version,
                expected_version_id=expected_version_id,
                task_id=task_id,
                created_by=user,
                was_impersonated=is_impersonated(request),
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except ObjectStorageError:
            return Response(
                {"detail": "Canvas source storage is temporarily unavailable; the layout was not saved."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        self._report_canvas_action(
            "canvas layout published",
            canvas,
            version_id=str(version.id),
            placement_count=len(layout.get("placements", [])),
            is_sandbox_publish=task_id is not None,
        )
        return Response(
            CanvasLayoutPublishResponseSerializer(
                instance={"canvas": canvas, "layout": layout, "current_version_id": str(version.id)}
            ).data
        )

    def _read_current_layout(self, canvas: Canvas) -> dict[str, Any]:
        """The canvas's head layout document, or the default empty layout before
        the first publish. Raises ObjectStorageError when storage is unavailable."""
        if canvas.current_source_version is None:
            return default_layout()
        return build_service.read_source_project(canvas.current_source_version)

    @extend_schema(
        operation_id="canvases_home_create",
        request=None,
        responses={
            200: OpenApiResponse(response=CanvasSerializer, description="The caller's existing home canvas."),
            201: OpenApiResponse(
                response=CanvasSerializer, description="A home canvas was provisioned for the caller."
            ),
            403: OpenApiResponse(description="Home is a viewer surface; sandbox tokens cannot provision it."),
        },
    )
    @action(methods=["POST"], detail=False)
    def home(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Get or provision the caller's home canvas.

        Idempotent: returns the user's existing home canvas, or creates a grid
        canvas in their personal channel and points their home preference at
        it. The home surface calls this on open.
        """
        user = self._request_user()
        if user is None or self._is_sandbox_authenticated(request):
            return Response(
                {"detail": "Home is a viewer surface; sandbox tokens cannot provision it."},
                status=status.HTTP_403_FORBIDDEN,
            )
        existing = self._home_canvas_for(user)
        if existing is not None:
            return Response(CanvasSerializer(existing).data)
        channel_id = tasks_facade.ensure_personal_channel_id(self.team_id, user.id)
        with transaction.atomic():
            # Serialize provisioning per user: two concurrent first-opens (two
            # tabs, or desktop plus web) would otherwise both miss the read above
            # and each create a "Home" canvas, leaving one orphaned. Re-read under
            # the lock so the loser returns the winner's canvas instead.
            self._lock_home_provisioning(user.id)
            existing = self._home_canvas_for(user)
            if existing is not None:
                return Response(CanvasSerializer(existing).data)
            canvas = Canvas.objects.create(
                team_id=self.team_id,
                channel_id=channel_id,
                name="Home",
                kind=Canvas.KIND_GRID,
                description="Your personal home canvas.",
                created_by=user,
            )
            CanvasHomePreference.objects.for_team(self.team_id).update_or_create(
                team_id=self.team_id, user=user, defaults={"canvas": canvas}
            )
        # Starter content is best-effort: an empty home still provisions when
        # object storage or the seed publish is unavailable.
        try:
            seed_home_canvas(canvas, user=user, channel_id=channel_id)
        except Exception:
            logger.exception("Failed to seed home canvas", canvas_id=str(canvas.id), team_id=self.team_id)
        self._log_canvas_activity(canvas, "created", Detail(name=canvas.name))
        self._report_canvas_action("canvas home provisioned", canvas)
        return Response(CanvasSerializer(canvas).data, status=status.HTTP_201_CREATED)

    def _lock_home_provisioning(self, user_id: int) -> None:
        """Serialize home provisioning for one user inside the current transaction.

        There is no preference row to lock before the first provision, so a
        transaction-scoped advisory lock guards the read-then-create window.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"canvas_home:{self.team_id}:{user_id}"],
            )

    def _home_canvas_for(self, user: User) -> Canvas | None:
        """The user's home canvas, or None when there is none to open.

        Deleting a canvas is a soft delete that leaves the pointer behind, so a
        pointer at a deleted canvas means "no home set", not a broken home.
        """
        preference = (
            CanvasHomePreference.objects.for_team(self.team_id).select_related("canvas").filter(user=user).first()
        )
        if preference is None or preference.canvas.deleted:
            return None
        return preference.canvas

    @extend_schema(
        operation_id="canvases_build_action_create",
        request=CanvasBuildActionSerializer,
        responses={
            200: CanvasBuildSerializer,
            429: OpenApiResponse(description="The team's build capacity is exhausted; retry shortly."),
        },
    )
    @action(methods=["POST"], detail=True, url_path="builds/action")
    def build_action(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Apply a lifecycle action (retry, pin, unpin, cancel) to one build."""
        canvas = self.get_object()
        payload = CanvasBuildActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            build = build_service.act_on_build(
                canvas, payload.validated_data["build_id"], payload.validated_data["action"]
            )
        except CanvasBuild.DoesNotExist:
            return Response({"detail": "Build not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        self._log_canvas_activity(
            canvas,
            f"build_{payload.validated_data['action']}",
            Detail(
                name=canvas.name,
                trigger=Trigger(
                    job_type="canvas_build",
                    job_id=str(build.id),
                    payload={"action": payload.validated_data["action"]},
                ),
            ),
        )
        return Response(CanvasBuildSerializer(build).data)

    @extend_schema(
        operation_id="canvases_report_error_create",
        request=CanvasReportErrorSerializer,
        responses={
            202: CanvasErrorReportResultSerializer,
            404: OpenApiResponse(description="Build not found for this canvas."),
        },
    )
    @action(methods=["POST"], detail=True)
    def report_error(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Report a runtime error observed while rendering a canvas build.

        Files the report in the authoring task's thread (deduped per build and
        error type) so the canvas's agent can be asked to fix it. Reports never
        start an agent run by themselves — dispatch is `request_fix`. Only the
        error class crosses the server; full messages and stacks stay
        client-side because rendering sessions can carry viewer data.
        """
        canvas = self.get_object()
        payload = CanvasReportErrorSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        build = self._canvas_build(canvas, payload.validated_data["build_id"])
        error_type = error_reports.sanitize_error_type(payload.validated_data["error_type"])
        outcome = error_reports.report_runtime_error(canvas, build, error_type)
        self._report_canvas_action(
            "canvas runtime error reported",
            canvas,
            build_id=str(build.id),
            error_type=error_type,
            report_outcome=outcome,
        )
        return Response({"report_outcome": outcome}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        operation_id="canvases_request_fix_create",
        request=CanvasRequestFixSerializer,
        responses={
            202: CanvasFixRequestResultSerializer,
            403: OpenApiResponse(
                description=(
                    "The caller is a sandbox (agents stage fixes directly as drafts), or is not the "
                    "authoring task's creator (only the creator can dispatch a run under their credentials)."
                )
            ),
            404: OpenApiResponse(description="Build not found for this canvas."),
            409: OpenApiResponse(description="The canvas has no authoring task to route the fix to."),
            429: OpenApiResponse(description="The team's compute quota is exhausted; retry later."),
        },
    )
    # task:write as well: the dispatched fix run executes with the creator's
    # credentials, so canvas:write alone must not be able to start or steer it —
    # consistent with the task-run endpoints themselves.
    @action(methods=["POST"], detail=True, required_scopes=["canvas:write", "task:write"])
    def request_fix(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Wake the canvas's authoring agent to fix a failing build or runtime error.

        Starts (or signals) an agent run on the authoring task, instructed to
        stage the fix as a draft the user reviews and promotes. This is the
        human-initiated dispatch step behind error reports; it spends agent
        compute, so it never fires automatically, and only the authoring
        task's creator may dispatch — the run executes with their credentials.
        """
        canvas = self.get_object()
        if self._is_sandbox_authenticated(request):
            return Response(
                {"detail": "Fix requests are human-initiated; agents stage fixes directly as drafts."},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = CanvasRequestFixSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        build = self._canvas_build(canvas, payload.validated_data["build_id"])
        task_id = error_reports.authoring_task_id(canvas, build)
        if task_id is None:
            return Response(
                {"detail": "This canvas has no authoring task to route the fix to."},
                status=status.HTTP_409_CONFLICT,
            )
        is_build_failure = build.status == CanvasBuild.STATUS_FAILED and not payload.validated_data.get("error_type")
        error_type = (
            error_reports.BUILD_FAILURE_ERROR_TYPE
            if is_build_failure
            else error_reports.sanitize_error_type(payload.validated_data.get("error_type"))
        )
        prompt = error_reports.build_fix_prompt(
            canvas,
            build_id=str(build.id),
            source_version_id=str(build.source_version_id) if build.source_version_id else None,
            error_type=error_type,
            origin="build" if is_build_failure else "runtime",
            error_codes=error_reports.diagnostic_error_codes(build.diagnostics),
        )
        user = self._request_user()
        outcome = tasks_facade.request_canvas_fix(
            task_id, self.team_id, prompt=prompt, acting_user_id=user.id if user else None
        )
        if outcome == "forbidden":
            return Response(
                {"detail": "Only the authoring task's creator can dispatch a fix."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if outcome == "not_found":
            return Response(
                {"detail": "The authoring task for this canvas no longer exists."},
                status=status.HTTP_409_CONFLICT,
            )
        if outcome == "organization_deactivated":
            return Response(
                {
                    "detail": "Your organization has been deactivated. Contact PostHog support if you think this is a mistake."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if outcome == "quota_exhausted":
            return Response(
                {"detail": "The team's compute quota is exhausted; retry later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        self._log_canvas_activity(
            canvas,
            "fix_requested",
            Detail(
                name=canvas.name,
                trigger=Trigger(
                    job_type="canvas_fix",
                    job_id=str(build.id),
                    payload={"error_type": error_type, "dispatch_outcome": outcome},
                ),
            ),
        )
        self._report_canvas_action(
            "canvas fix requested",
            canvas,
            build_id=str(build.id),
            error_type=error_type,
            dispatch_outcome=outcome,
        )
        return Response(
            {"dispatch_outcome": outcome, "task_id": str(task_id)},
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        operation_id="canvases_request_agent_create",
        request=CanvasAgentRequestSerializer,
        responses={
            202: CanvasAgentRequestResultSerializer,
            403: OpenApiResponse(description="Agent requests are not declared or the caller is a sandbox."),
            409: OpenApiResponse(description="The canvas has no authoring task."),
            429: OpenApiResponse(
                description=(
                    "The request was denied for compute: the team's quota is exhausted (retry later), "
                    "or the organization is deactivated (not retryable)."
                )
            ),
        },
    )
    # task:write as well: the dispatched run executes with the creator's
    # credentials, so canvas:write alone must not be able to start or steer it —
    # consistent with the task-run endpoints themselves.
    @action(methods=["POST"], detail=True, required_scopes=["canvas:write", "task:write"])
    def request_agent(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Route a viewer-approved change request to the canvas's authoring task."""
        canvas = self.get_object()
        if self._is_sandbox_authenticated(request):
            return Response(
                {"detail": "Agent requests must be approved by a viewer."},
                status=status.HTTP_403_FORBIDDEN,
            )
        capabilities = canvas.current_source_version.capabilities if canvas.current_source_version else None
        if not bool(((capabilities or {}).get("posthog") or {}).get("agentRequests")):
            return Response(
                {"detail": "This canvas has not declared agent requests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = CanvasAgentRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        task_id = error_reports.authoring_task_id(canvas, canvas.published_build)
        if task_id is None:
            return Response(
                {"detail": "This canvas has no authoring task to receive the request."},
                status=status.HTTP_409_CONFLICT,
            )
        user = self._request_user()
        outcome = tasks_facade.request_canvas_change(
            task_id,
            self.team_id,
            prompt=error_reports.build_agent_request_prompt(canvas, payload.validated_data["prompt"]),
            viewer_prompt=payload.validated_data["prompt"],
            acting_user_id=user.id if user else None,
        )
        if outcome == "not_found":
            return Response(
                {"detail": "The authoring task for this canvas no longer exists."},
                status=status.HTTP_409_CONFLICT,
            )
        if outcome == "organization_deactivated":
            return Response(
                {
                    "detail": "Your organization has been deactivated. Contact PostHog support if you think this is a mistake."
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        if outcome == "quota_exhausted":
            return Response(
                {"detail": "The team's compute quota is exhausted; retry later."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        self._log_canvas_activity(
            canvas,
            "agent_requested",
            Detail(
                name=canvas.name,
                trigger=Trigger(
                    job_type="canvas_agent_request",
                    job_id=str(task_id),
                    payload={"request_outcome": outcome},
                ),
            ),
        )
        self._report_canvas_action(
            "canvas agent requested",
            canvas,
            request_outcome=outcome,
        )
        return Response(
            CanvasAgentRequestResultSerializer(instance={"request_outcome": outcome, "task_id": task_id}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    def _canvas_build(self, canvas: Canvas, build_id: UUID) -> CanvasBuild:
        """Resolve one of this canvas's builds, or 404."""
        build = (
            CanvasBuild.objects.for_team(self.team_id)
            .select_related("source_version")
            .filter(id=build_id, canvas_id=canvas.id)
            .first()
        )
        if build is None:
            raise NotFound("Build not found for this canvas.")
        return build

    def _state_actor(self, request: Request) -> User | None:
        """The user whose personal state is read or written."""
        return self._request_user()

    @extend_schema(
        operation_id="canvases_actions_retrieve",
        responses={200: CanvasActionsResponseSerializer},
    )
    @action(methods=["GET"], detail=False, url_path="actions")
    def actions(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """List the action registry: every verb a canvas may declare and invoke."""
        rows = [
            {"verb": entry.verb, "summary": entry.summary, "destructive": entry.destructive, "usage": entry.usage}
            for entry in sorted(CANVAS_ACTIONS.values(), key=lambda entry: entry.verb)
        ]
        return Response(CanvasActionsResponseSerializer(instance={"actions": rows}).data)

    @extend_schema(
        operation_id="canvases_actions_invoke",
        request=CanvasActionInvokeSerializer,
        responses={
            200: CanvasActionResultSerializer,
            400: OpenApiResponse(description="Unknown verb, or the payload failed the verb's schema."),
            403: OpenApiResponse(
                description="The verb is not declared in the canvas's capabilities, actions are disabled for the "
                "team, or the caller is a sandbox."
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="actions/invoke")
    def invoke_action(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Invoke one registered action verb as the viewer.

        The canvas must declare the verb in capabilities.posthog.actions (the
        reviewed permission boundary); the write itself runs with the viewer's
        own permissions, exactly as if they acted in the app.
        """
        canvas = self.get_object()
        user = self._state_actor(request)
        if user is None:
            return Response(
                {"detail": "Canvas actions are invoked by viewers; sandbox tokens cannot use them."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if canvas_actions_disabled(self.team):
            return Response(
                {"detail": "Canvas actions are disabled for this team."},
                status=status.HTTP_403_FORBIDDEN,
            )
        payload = CanvasActionInvokeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        verb = payload.validated_data["verb"]
        entry = CANVAS_ACTIONS.get(verb)
        if entry is None:
            return Response(
                {"detail": f'Unknown action verb "{verb}". Registered verbs: {", ".join(sorted(CANVAS_ACTIONS))}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        version = canvas.current_source_version
        if verb not in declared_actions(version.capabilities if version else None):
            return Response(
                {
                    "detail": f'The canvas does not declare action "{verb}". '
                    "Add it to capabilities.posthog.actions and publish."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        verb_payload = entry.payload_serializer(data=payload.validated_data["payload"])
        verb_payload.is_valid(raise_exception=True)
        try:
            result = entry.execute(self.team_id, user.id, canvas, verb_payload.validated_data)
        except ValueError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        # Every execution is audited: the trigger names the verb, the activity
        # log row names the viewer it ran as.
        self._log_canvas_activity(
            canvas,
            "action_invoked",
            Detail(
                name=canvas.name,
                trigger=Trigger(job_type="canvas_action", job_id=verb, payload={"verb": verb}),
            ),
        )
        self._report_canvas_action("canvas action invoked", canvas, verb=verb)
        return Response(CanvasActionResultSerializer(instance={"verb": verb, "result": result}).data)

    @extend_schema(
        operation_id="canvases_state_retrieve",
        parameters=[
            OpenApiParameter(
                "scope",
                OpenApiTypes.STR,
                required=False,
                enum=CanvasState.SCOPES,
                description="Only return entries in this scope.",
            )
        ],
        responses={
            200: CanvasStateResponseSerializer,
            403: OpenApiResponse(description="Canvas state requires an authenticated user."),
        },
    )
    @action(methods=["GET"], detail=True)
    def state(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Read the canvas's runtime key-value state (the ph.state store).

        Returns shared entries plus the authenticated user's own user-scoped
        entries — never another user's.
        """
        canvas = self.get_object()
        user = self._state_actor(request)
        if user is None:
            return _state_rejection()
        # Reads honor the same reviewed boundary as writes: a canvas only sees
        # the scopes its head version declares, so narrowing capabilities also
        # stops reads of previously written entries.
        version = canvas.current_source_version
        declared = declared_state_scopes(version.capabilities if version else None)
        readable_entries = Q(scope=CanvasState.SCOPE_SHARED, user__isnull=True) | Q(
            scope=CanvasState.SCOPE_USER, user=user
        )
        entries = CanvasState.objects.for_team(self.team_id).filter(readable_entries, canvas=canvas, scope__in=declared)
        scope = request.query_params.get("scope")
        if scope:
            if scope not in CanvasState.SCOPES:
                return Response({"detail": "scope must be 'user' or 'shared'."}, status=status.HTTP_400_BAD_REQUEST)
            entries = entries.filter(scope=scope)
        return Response(CanvasStateResponseSerializer(instance={"entries": entries.order_by("scope", "key")}).data)

    @extend_schema(
        operation_id="canvases_state_set",
        request=CanvasStateSetSerializer,
        responses={
            200: CanvasStateEntrySerializer,
            204: OpenApiResponse(description="The key was deleted (value was null)."),
            400: OpenApiResponse(description="The value or the scope's key count exceeds the state bounds."),
            403: OpenApiResponse(
                description="The scope is not declared in the canvas's capabilities, or the caller is a sandbox."
            ),
        },
    )
    @action(methods=["POST"], detail=True, url_path="state/set")
    def set_state(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Write one key of the canvas's runtime state, or delete it with a null value."""
        canvas = self.get_object()
        user = self._state_actor(request)
        if user is None:
            return _state_rejection()
        payload = CanvasStateSetSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        scope = payload.validated_data["scope"]
        key = payload.validated_data["key"]
        value = payload.validated_data["value"]
        # The head version's declared capabilities gate writes: state is part of
        # the canvas's reviewed permission boundary, exactly like insights.
        version = canvas.current_source_version
        declared = declared_state_scopes(version.capabilities if version else None)
        if scope not in declared:
            return Response(
                {
                    "detail": f'The canvas does not declare state scope "{scope}". '
                    "Add it to capabilities.posthog.state and publish."
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        owner = user if scope == CanvasState.SCOPE_USER else None
        scoped = CanvasState.objects.for_team(self.team_id).filter(canvas=canvas, scope=scope, user=owner)
        existing = scoped.filter(key=key)
        if value is None:
            existing.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        if len(json.dumps(value, separators=(",", ":")).encode()) > CANVAS_STATE_MAX_VALUE_BYTES:
            return Response(
                {
                    "detail": f"State values are capped at {CANVAS_STATE_MAX_VALUE_BYTES // 1024} KB serialized. "
                    "Store large data in PostHog (insights, the warehouse) and reference it."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            # The canvas row is the mutex for the key-count check: without it,
            # concurrent new-key writes both observe space and overshoot the cap.
            Canvas.objects.for_team(self.team_id).select_for_update().get(pk=canvas.pk)
            if not existing.exists():
                if scoped.count() >= CANVAS_STATE_MAX_KEYS_PER_SCOPE:
                    return Response(
                        {
                            "detail": f"A canvas may hold at most {CANVAS_STATE_MAX_KEYS_PER_SCOPE} state keys "
                            "per scope. Delete keys (set them to null) or consolidate values."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            entry, _ = CanvasState.objects.for_team(self.team_id).update_or_create(
                team_id=self.team_id, canvas=canvas, scope=scope, user=owner, key=key, defaults={"value": value}
            )
        return Response(CanvasStateEntrySerializer(entry).data)

    def _log_canvas_activity(self, canvas: Canvas, activity: str, detail: Detail) -> None:
        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
            user=self._request_user(),
            was_impersonated=is_impersonated(self.request),
            item_id=canvas.id,
            scope="Canvas",
            activity=activity,
            detail=detail,
        )

    def _report_canvas_action(self, event: str, canvas: Canvas, **extra: Any) -> None:
        user = self._request_user()
        if user:
            report_user_action(
                user,
                event,
                {"canvas_id": str(canvas.id), "channel_id": str(canvas.channel_id), **extra},
                team=self.team,
                request=self.request,
            )

    def _request_user(self) -> User | None:
        """The requesting real user, or None for anonymous/service principals."""
        user = self.request.user
        return user if isinstance(user, User) else None

    @staticmethod
    def _request_task_id(request: Request) -> UUID | None:
        """The publishing task's id, when the sandbox stamped one on the call."""
        raw_task_id = (request.headers.get("X-PostHog-Task-Id") or "").strip()
        try:
            return UUID(raw_task_id)
        except ValueError:
            return None

    def _sandbox_task_id(self, request: Request) -> UUID | None:
        """Return the calling sandbox's task when its header matches the OAuth binding."""
        task_id = self._request_task_id(request)
        if task_id is None or not self._is_sandbox_authenticated(request):
            return None
        authenticator = cast(OAuthAccessTokenAuthentication, request.successful_authenticator)
        if authenticator.access_token.sandbox_task_id != task_id:
            return None
        return task_id if tasks_facade.task_exists(task_id, self.team_id) else None

    def _announce_canvas_created(self, task_id: UUID | None, user: User | None, canvas: Canvas) -> None:
        """Announce a canvas's first publish in the generating task's thread.

        ``task_id`` is the sandbox-bound id from ``_sandbox_task_id``; None (a
        human or app save) means no announcement.
        """
        if task_id is None:
            return
        tasks_facade.post_canvas_created_thread_update(
            task_id,
            self.team_id,
            acting_user_id=user.id if user else None,
            canvas_name=canvas.name or "Canvas",
            canvas_url=canvas_url(canvas),
        )

    @staticmethod
    def _is_sandbox_authenticated(request: Request) -> bool:
        """True when the request bears an OAuth token minted for a task sandbox —
        the credential a task sandbox (via the MCP server) calls this API with.

        The sandbox apps also issue the desktop app's interactive grants, so the application
        alone does not prove sandbox origin. Server-minted tokens carry either a task binding
        or the internal provenance scope. An unbound server token must still fail closed rather
        than inherit its user's Canvas visibility.
        """
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            return False
        access_token = authenticator.access_token
        scopes = set((access_token.scope or "").split())
        if access_token.sandbox_task_id is None and "internal_run:read" not in scopes:
            return False
        application = access_token.application
        return application is not None and application.client_id in SANDBOX_OAUTH_APP_CLIENT_IDS
