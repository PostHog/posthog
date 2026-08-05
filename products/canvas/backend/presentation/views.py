from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models.user import User
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.canvas.backend import build_service
from products.canvas.backend.models import Canvas, CanvasBuild, CanvasSourceVersion
from products.canvas.backend.presentation.serializers import (
    CanvasBuildActionSerializer,
    CanvasBuildSerializer,
    CanvasBuildsResponseSerializer,
    CanvasCreateSerializer,
    CanvasPublishConflictSerializer,
    CanvasRevertSerializer,
    CanvasSerializer,
    CanvasSourceEditSerializer,
    CanvasSourceInvalidSerializer,
    CanvasSourcePublishResponseSerializer,
    CanvasSourcePublishSerializer,
    CanvasSourceResponseSerializer,
    CanvasSummarySerializer,
    CanvasUpdateSerializer,
    CanvasValidateRequestSerializer,
    CanvasValidateResponseSerializer,
    CanvasVersionSerializer,
)
from products.canvas.backend.source import apply_source_edits, has_errors, validate_source_project
from products.tasks.backend.facade import api as tasks_facade

# The canvas's build lifecycle returns this many recent builds (the published
# build is unioned in even when it has aged past the window).
BUILDS_WINDOW = 20
# Version-history window for the client's undo/revert browser.
VERSIONS_WINDOW = 100


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


class CanvasViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Canvases: agent-built sandboxed browser apps, filed into channels.

    Source is versioned per publish and built server-side; the canvas app
    renders the published build's artifact from the isolated artifact origin.
    """

    scope_object = "canvas"
    # unscoped() because a class attribute is built before any team context
    # exists; safely_get_queryset applies the team filter explicitly.
    queryset = Canvas.objects.unscoped().select_related("created_by")
    serializer_class = CanvasSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    scope_object_read_actions = ["list", "retrieve", "source", "versions", "builds", "validate"]
    scope_object_write_actions = [
        "create",
        "partial_update",
        "destroy",
        "publish",
        "edit",
        "revert",
        "build_action",
    ]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "channel", OpenApiTypes.UUID, required=False, description="Only return canvases in this channel."
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.filter(team_id=self.team_id, deleted=False)
        # Channels are per-user for the personal kind: the facade's visibility
        # rule makes a canvas filed into someone else's personal channel
        # invisible (and unwritable) to everyone but its owner, for list and
        # every detail action alike. The create() check alone is not enough —
        # DRF resolves all detail actions off this queryset.
        user = self._request_user()
        queryset = queryset.filter(tasks_facade.visible_channels_q(user.id if user else None, relation="channel"))
        if self.action == "list":
            channel_id = self.request.query_params.get("channel")
            if channel_id:
                try:
                    channel_id = str(UUID(channel_id))
                except ValueError:
                    return queryset.none()
                queryset = queryset.filter(channel_id=channel_id)
        return queryset.order_by("-created_at")

    @extend_schema(
        operation_id="canvases_create",
        request=CanvasCreateSerializer,
        responses={201: CanvasSerializer},
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
        canvas = Canvas.objects.create(
            team_id=self.team_id,
            channel_id=channel_id,
            name=payload.validated_data["name"],
            template_id=payload.validated_data["template_id"],
            created_by=user,
            # A sandbox-created canvas is its task's deliverable: bind
            # the two at birth so the client can show the run on the
            # canvas and nest the task under it — composer-initiated
            # generations have no client-side create to record it.
            generation_task_id=self._sandbox_task_id(request),
        )
        return Response(CanvasSerializer(canvas).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="canvases_partial_update",
        request=CanvasUpdateSerializer,
        responses={200: CanvasSerializer},
    )
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Update canvas metadata (name, author context, pin, generation-task pointer)."""
        canvas = self.get_object()
        payload = CanvasUpdateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        update_fields = ["updated_at"]
        if "name" in data:
            canvas.name = data["name"]
            update_fields.append("name")
        if "context" in data:
            canvas.context = data["context"]
            update_fields.append("context")
        if "pinned" in data:
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
        return Response(CanvasSerializer(canvas).data)

    def perform_destroy(self, instance: Canvas) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted", "updated_at"])

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
        """The canvas's source-version history, newest first (metadata only)."""
        canvas = self.get_object()
        versions = canvas.source_versions.select_related("created_by").order_by("-created_at")[:VERSIONS_WINDOW]
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
        self.get_object()
        payload = CanvasValidateRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        diagnostics = validate_source_project(payload.validated_data["project"])
        return Response({"valid": not has_errors(diagnostics), "diagnostics": diagnostics})

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
        diagnostics = validate_source_project(project)
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
                created_by_id=user.id if user else None,
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

        return Response(
            {
                "canvas": CanvasSummarySerializer(canvas).data,
                "current_version_id": str(version.id),
                "diagnostics": diagnostics,
            }
        )

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
            _canvas, build = build_service.revert_to_version(
                canvas,
                payload.validated_data["version_id"],
                payload.validated_data["expected_current_version_id"],
            )
        except build_service.CanvasVersionConflict as conflict:
            return _conflict_response(conflict)
        except build_service.CanvasBuildCapacityExceeded:
            return _capacity_response()
        except CanvasSourceVersion.DoesNotExist:
            return Response({"detail": "Version not found for this canvas."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CanvasBuildSerializer(build).data)

    @extend_schema(
        operation_id="canvases_builds_retrieve",
        responses={200: CanvasBuildsResponseSerializer},
        request=None,
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
        response = {
            "published_build_id": str(canvas.published_build_id) if canvas.published_build_id else None,
            "current_version_id": (str(canvas.current_source_version_id) if canvas.current_source_version_id else None),
            "builds": CanvasBuildSerializer(builds, many=True).data,
        }
        return Response(response)

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
        return Response(CanvasBuildSerializer(build).data)

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
        """The calling task's id when this is a sandbox-stamped MCP call for a
        task in this team; None for human/app saves. The task sandbox stamps
        every MCP call with an X-PostHog-Task-Id header, but the header alone
        is forgeable, so two checks bind it to a real sandbox run: the request
        must carry an OAuth token minted under a sandbox app (those tokens are
        only created server-side), and the task must have been created by the
        requesting user (the sandbox authenticates with the task creator's
        credentials)."""
        task_id = self._request_task_id(request)
        if task_id is None or not self._is_sandbox_authenticated(request):
            return None
        user = self._request_user()
        if user is None or not tasks_facade.task_owned_by_user(task_id, self.team_id, user.id):
            return None
        return task_id

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
            canvas_url=f"{settings.SITE_URL}/code/canvas/{canvas.channel_id}/{canvas.id}",
        )

    @staticmethod
    def _is_sandbox_authenticated(request: Request) -> bool:
        """True when the request bears an OAuth token minted under a sandbox app —
        the credential a task sandbox (via the MCP server) calls this API with."""
        authenticator = request.successful_authenticator
        if not isinstance(authenticator, OAuthAccessTokenAuthentication):
            return False
        application = authenticator.access_token.application
        return application is not None and application.client_id in SANDBOX_OAUTH_APP_CLIENT_IDS
