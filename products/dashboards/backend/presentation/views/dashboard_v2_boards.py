from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.exceptions import Conflict
from posthog.models.user import User
from posthog.permissions import dashboard_v2_enabled, is_service_auth

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.dashboards.backend.facade import api
from products.dashboards.backend.facade.contracts import (
    MAX_BOARD_SPEC_BYTES,
    BoardDetail,
    BoardListAccess,
    BoardNotFound,
    BoardReadOnly,
    BoardSpecInvalid,
    BoardSummary,
    BoardVersionConflict,
)
from products.dashboards.backend.facade.enums import BoardManagedBy


@extend_schema_field({"type": "object", "additionalProperties": True})
class BoardSpecField(serializers.JSONField):
    """A `dashboard-v2` document: `{version: 2, title, tabs: [...]}`. Stored as sent."""

    def to_internal_value(self, data: Any) -> Any:
        if not isinstance(data, dict):
            raise serializers.ValidationError("The board document must be a JSON object.")
        return super().to_internal_value(data)


class BoardSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The board's row id. Object access rules on the `dashboard` resource use it.")
    uid = serializers.CharField(help_text="Identifier of the board in URLs. Unique among the project's live boards.")
    title = serializers.CharField(help_text="The document's `title` when it was last saved.")
    tags = serializers.ListField(
        child=serializers.CharField(), help_text="The document's `tags` when it was last saved."
    )
    folder = serializers.CharField(
        allow_blank=True, help_text="The document's `folder`: folder titles separated by `/`. Empty for the top level."
    )
    version = serializers.IntegerField(
        help_text=(
            "Counts saves: starts at 1, and each save adds 1. Send it as `base_version` to refuse a save over a "
            "newer one. Not the document's schema version, which is `spec.version`."
        )
    )
    managed_by = serializers.ChoiceField(
        choices=BoardManagedBy.choices,
        help_text="`native` boards are saved through this API. Other boards are read-only here.",
    )
    template_id = serializers.CharField(allow_null=True, help_text="The template the board was made from, or null.")
    template_version = serializers.IntegerField(
        allow_null=True, help_text="The version of `template_id` the board was made from, or null."
    )
    created_at = serializers.DateTimeField(help_text="When the board was first saved.")
    created_by_id = serializers.IntegerField(allow_null=True, help_text="ID of the user who created the board.")
    last_modified_at = serializers.DateTimeField(help_text="When the board was last saved.")
    last_modified_by_id = serializers.IntegerField(
        allow_null=True, help_text="ID of the user who last saved the board."
    )


class BoardDetailSerializer(BoardSummarySerializer):
    spec = BoardSpecField(help_text="The whole board document, upgraded to the current schema version.")


class BoardCreateSerializer(serializers.Serializer):
    spec = BoardSpecField(
        help_text=(
            "The board document, at most "
            f"{MAX_BOARD_SPEC_BYTES} bytes. `version` is its schema version, currently 2. It is upgraded to the "
            "current schema version before it is saved. Tiles are not checked, so a broken tile shows as an error "
            "tile, and unknown fields are kept."
        )
    )


class BoardUpdateSerializer(BoardCreateSerializer):
    base_version = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text=(
            "The `version` this save is based on. When the board is at another version, nothing is saved and the "
            "response is a 409. Leave it out to save over any version."
        ),
    )


_NOT_FOUND = OpenApiResponse(description="No live board in this project has this uid, or dashboards v2 is off.")
_INVALID = OpenApiResponse(description="The document's schema version is unknown, or it is over the size limit.")
_READ_ONLY = OpenApiResponse(description="The board is built in or managed from code, so it cannot change here.")


class DashboardV2BoardViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Saved `dashboard-v2` boards. Each board is one JSON document."""

    # Boards share the `dashboard` resource: resource-level access to dashboards covers boards too, and an object
    # rule names a board by its row UUID, which never equals a classic dashboard's integer id.
    scope_object = "dashboard"
    pagination_class = FacadeLimitOffsetPagination
    serializer_class = BoardDetailSerializer
    lookup_field = "uid"
    path_parameters = {"uid": PathParameter(type=str, description="The `uid` of the board.")}

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        # 404, not 403, so a project without the flag cannot tell the endpoint exists.
        if not dashboard_v2_enabled(self.team, request.user):
            raise exceptions.NotFound()
        # Boards belong to the project's root team. A child environment would check its own rules but
        # read and write the root team's rows, so it gets a 404 too.
        if self.team.pk != self.team.project_id:
            raise exceptions.NotFound()

    def read_object(self) -> BoardDetail | None:
        try:
            return api.get_board(self.team_id, self.kwargs["uid"])
        except BoardNotFound:
            return None

    def object_access_ref(self, record: BoardSummary) -> ObjectAccessRef:
        return ObjectAccessRef(
            resource="dashboard", id=str(record.id), team_id=record.team_id, created_by_id=record.created_by_id
        )

    def _list_access(self) -> BoardListAccess | None:
        if is_service_auth(self.request):
            return None
        # Org admins have implicit access to every dashboard, so the list must match retrieve, as for classic ones.
        access = self.user_access_control.list_access_filter("dashboard", include_all_if_admin=True)
        if access is None:
            return None
        return BoardListAccess(
            viewer_id=cast(User, self.request.user).id,
            only_allowed=access.only_allowed,
            allowed_ids=access.allowed_ids,
            blocked_ids=access.blocked_ids,
        )

    @extend_schema(responses={200: BoardSummarySerializer(many=True), 404: _NOT_FOUND})
    def list(self, request: Request, **kwargs: Any) -> Response:
        """List the project's boards, the most recently saved first. Rows leave out the document."""
        return facade_page_response(
            self,
            lambda page: api.list_boards(self.team_id, page, self._list_access()),
            serializer_class=BoardSummarySerializer,
        )

    @validated_request(
        request_serializer=BoardCreateSerializer,
        responses={201: OpenApiResponse(response=BoardDetailSerializer), 400: _INVALID, 404: _NOT_FOUND},
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        """Save a document as a new board at version 1."""
        try:
            board = api.create_board(self.team_id, cast(User, request.user).id, request.validated_data["spec"])
        except BoardSpecInvalid as error:
            raise exceptions.ValidationError({"spec": str(error)}, code="invalid_spec")
        return Response(BoardDetailSerializer(board).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: BoardDetailSerializer, 404: _NOT_FOUND})
    def retrieve(self, request: Request, uid: str, **kwargs: Any) -> Response:
        """Get a board with its document."""
        return Response(BoardDetailSerializer(self.get_object()).data)

    @validated_request(
        request_serializer=BoardUpdateSerializer,
        responses={
            200: OpenApiResponse(response=BoardDetailSerializer),
            400: _INVALID,
            403: _READ_ONLY,
            404: _NOT_FOUND,
            409: OpenApiResponse(description="The board is not at `base_version`. Nothing was saved."),
        },
    )
    def update(self, request: ValidatedRequest, uid: str, **kwargs: Any) -> Response:
        """Replace a board's document and add 1 to its version."""
        self.get_object()
        try:
            board = api.update_board(
                self.team_id,
                uid,
                cast(User, request.user).id,
                request.validated_data["spec"],
                request.validated_data.get("base_version"),
            )
        except BoardSpecInvalid as error:
            raise exceptions.ValidationError({"spec": str(error)}, code="invalid_spec")
        except BoardNotFound:
            raise exceptions.NotFound()
        except BoardReadOnly:
            raise exceptions.PermissionDenied("This board is read-only.")
        except BoardVersionConflict as error:
            raise Conflict(
                f"The board is at version {error.current_version}, and this save is based on version "
                f"{error.base_version}. Load the board again and redo the change.",
                code="version_conflict",
            )
        return Response(BoardDetailSerializer(board).data)

    @extend_schema(responses={204: None, 403: _READ_ONLY, 404: _NOT_FOUND})
    def destroy(self, request: Request, uid: str, **kwargs: Any) -> Response:
        """Delete a board. Its uid can then be reused."""
        self.get_object()
        try:
            api.delete_board(self.team_id, uid, cast(User, request.user).id)
        except BoardNotFound:
            raise exceptions.NotFound()
        except BoardReadOnly:
            raise exceptions.PermissionDenied("This board is read-only.")
        return Response(status=status.HTTP_204_NO_CONTENT)
