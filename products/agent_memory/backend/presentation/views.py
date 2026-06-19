"""DRF views for the agent-memory tree.

Humans (via the app), Slack, and any API client list, read, write, and delete
files in a team's shared memory tree here. The viewset only validates input and
calls the facade — no business logic.

The facade exposes async functions; these sync views bridge via `async_to_sync`.
File paths can contain slashes, so they travel as a `path` query param or body
field rather than as a URL `pk`.
"""

from typing import cast

from asgiref.sync import async_to_sync
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin

from ..facade import api
from .serializers import (
    MemoryAppendInputSerializer,
    MemoryConflictResponseSerializer,
    MemoryDeleteResponseSerializer,
    MemoryFileSerializer,
    MemoryFileSummarySerializer,
    MemoryWriteInputSerializer,
)


def _user_id(request: Request) -> int | None:
    user = request.user
    return cast(int, user.id) if getattr(user, "is_authenticated", False) else None


class AgentMemoryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """A team's shared, file-tree-based agent memory.

    Markdown files keyed by relative path (e.g. 'project.md', 'users/jane-doe.md',
    'scouts/<skill>/scratchpad.md'). Writes use optimistic concurrency: pass the
    `expected_version` you last read; a mismatch returns 409 so you re-read and merge.
    Prefer `append` for safe section-level edits that never clobber concurrent writes.
    """

    scope_object = "agent_memory"
    scope_object_read_actions = ["list", "read"]
    scope_object_write_actions = ["write", "append", "delete_file"]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "prefix",
                OpenApiTypes.STR,
                required=False,
                description="Only return files whose path starts with this fragment, e.g. 'scouts/' or 'users/'.",
            ),
        ],
        responses={200: MemoryFileSummarySerializer(many=True)},
    )
    def list(self, request: Request, **kwargs) -> Response:
        """List the team's memory files (metadata only, no bodies)."""
        prefix = request.query_params.get("prefix")
        summaries = async_to_sync(api.alist_memory)(team_id=self.team_id, prefix=prefix)
        return Response(MemoryFileSummarySerializer(instance=summaries, many=True).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                required=True,
                description="Relative path of the file to read, e.g. 'project.md'.",
            ),
        ],
        responses={
            200: MemoryFileSerializer,
            404: OpenApiResponse(description="No file at that path"),
        },
    )
    @action(detail=False, methods=["get"])
    def read(self, request: Request, **kwargs) -> Response:
        """Read a single memory file by path."""
        path = request.query_params.get("path")
        if not path:
            return Response({"detail": "path query param required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            memory_file = async_to_sync(api.aread_memory)(team_id=self.team_id, path=path)
        except api.InvalidMemoryPathError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.MemoryFileNotFoundError:
            return Response({"detail": "Memory file not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(MemoryFileSerializer(instance=memory_file).data)

    @extend_schema(
        request=MemoryWriteInputSerializer,
        responses={
            200: MemoryFileSerializer,
            400: OpenApiResponse(description="Invalid path or content"),
            409: OpenApiResponse(response=MemoryConflictResponseSerializer, description="Version conflict"),
        },
    )
    @action(detail=False, methods=["post"])
    def write(self, request: Request, **kwargs) -> Response:
        """Compare-and-set write of a whole file. Returns 409 on a version mismatch."""
        serializer = MemoryWriteInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            memory_file = async_to_sync(api.awrite_memory)(
                team_id=self.team_id,
                path=data["path"],
                content=data["content"],
                expected_version=data.get("expected_version"),
                updated_by_id=_user_id(request),
                updated_by_run=data.get("updated_by_run"),
            )
        except api.InvalidMemoryPathError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.MemoryContentTooLargeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.MemoryVersionConflictError as e:
            return Response(
                {
                    "detail": str(e),
                    "code": "version_conflict",
                    "path": e.path,
                    "expected_version": e.expected_version,
                    "actual_version": e.actual_version,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(MemoryFileSerializer(instance=memory_file).data)

    @extend_schema(
        request=MemoryAppendInputSerializer,
        responses={
            200: MemoryFileSerializer,
            400: OpenApiResponse(description="Invalid path, heading, or content"),
        },
    )
    @action(detail=False, methods=["post"])
    def append(self, request: Request, **kwargs) -> Response:
        """Append or replace a single markdown section atomically — never clobbers concurrent edits."""
        serializer = MemoryAppendInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            memory_file = async_to_sync(api.aappend_section)(
                team_id=self.team_id,
                path=data["path"],
                heading=data["heading"],
                body=data["body"],
                updated_by_id=_user_id(request),
                updated_by_run=data.get("updated_by_run"),
            )
        except api.InvalidMemoryPathError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except api.MemoryContentTooLargeError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MemoryFileSerializer(instance=memory_file).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "path",
                OpenApiTypes.STR,
                required=True,
                description="Relative path of the file to delete.",
            ),
        ],
        responses={200: MemoryDeleteResponseSerializer},
    )
    @action(detail=False, methods=["delete"], url_path="file")
    def delete_file(self, request: Request, **kwargs) -> Response:
        """Delete a memory file. Idempotent — deleting a missing file returns deleted=false."""
        path = request.query_params.get("path")
        if not path:
            return Response({"detail": "path query param required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            deleted = async_to_sync(api.adelete_memory)(team_id=self.team_id, path=path)
        except api.InvalidMemoryPathError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(MemoryDeleteResponseSerializer(instance={"deleted": deleted}).data)
