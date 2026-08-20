from typing import cast

from django.utils.functional import cached_property

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import APIScopePermission

from products.canvas.backend.models import Canvas
from products.canvas.backend.presentation.serializers import _CANVAS_URL_HELP_TEXT, canvas_url
from products.tasks.backend.facade import api as tasks_facade


class CanvasLocationSerializer(serializers.Serializer):
    """Where a canvas lives: the project and organization that own it."""

    canvas_id = serializers.UUIDField(help_text="Id of the canvas that was looked up.")
    canvas_name = serializers.CharField(help_text="Display name of the canvas.")
    channel_id = serializers.UUIDField(help_text="Id of the channel the canvas is filed into.")
    project_id = serializers.IntegerField(
        help_text=(
            "Id of the project that owns the canvas. Use it as the project_id path segment on "
            "/api/projects/<project_id>/canvases/ to read the canvas itself."
        )
    )
    project_name = serializers.CharField(help_text="Display name of the owning project.")
    organization_id = serializers.UUIDField(help_text="Id of the organization the owning project belongs to.")
    organization_name = serializers.CharField(help_text="Display name of that organization.")
    url = serializers.URLField(help_text=_CANVAS_URL_HELP_TEXT)


class CanvasLocationViewSet(viewsets.ViewSet):
    """Resolve which project owns a canvas, for clients holding only a share link.

    A canvas share link carries the channel and canvas ids but no project, while reading the
    canvas needs one. A client that lands on the wrong project has no other way to find out
    where the canvas actually lives.
    """

    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "canvas"
    http_method_names = ["get", "head", "options"]

    @cached_property
    def _canvas(self) -> Canvas:
        """The canvas, resolved through every access gate at once.

        A canvas that does not exist, lives in a project this user cannot reach, sits in
        someone else's personal channel, or is soft-deleted are all the same 404. Separating
        them would turn this endpoint into an oracle for which canvas ids exist.
        """
        user = cast(User, self.request.user)
        canvas = (
            # unscoped() because a root route carries no team-scope context; the team filter
            # below is what replaces it.
            Canvas.objects.unscoped()
            .filter(id=self.kwargs["pk"], deleted=False)
            # user.teams already accounts for org membership and project-level RBAC.
            .filter(team__in=user.teams)
            # A canvas inherits its channel's visibility, and a personal channel is visible
            # only to its creator.
            .filter(tasks_facade.visible_channels_q(user.id, relation="channel"))
            .select_related("team", "team__organization")
            .first()
        )
        if canvas is None:
            raise NotFound()
        return canvas

    @property
    def team(self) -> Team:
        """The owning team, which APIScopePermission reads to enforce a token's scoped_teams.

        Without it, any token carrying scoped_teams is rejected outright as "not a project-based
        endpoint". Exposing the resolved team instead gives the right semantic: such a token
        learns where a canvas lives only when it was granted that project.
        """
        return self._canvas.team

    @extend_schema(
        operation_id="canvas_locations_retrieve",
        summary="Find the project that owns a canvas",
        description=(
            "Resolve a canvas id to the project and organization that own it, without knowing the "
            "project up front. For clients that hold only a canvas share link "
            "(/code/canvas/<channel_id>/<canvas_id>) and need to know which project to open. "
            "Returns 404 for any canvas the caller cannot read, including canvases in projects "
            "they cannot access."
        ),
        responses={
            200: CanvasLocationSerializer,
            404: OpenApiResponse(description="No canvas with this id is visible to the caller."),
        },
    )
    def retrieve(self, request: Request, pk: str) -> Response:
        canvas = self._canvas
        return Response(
            CanvasLocationSerializer(
                {
                    "canvas_id": canvas.id,
                    "canvas_name": canvas.name,
                    "channel_id": canvas.channel_id,
                    "project_id": canvas.team_id,
                    "project_name": canvas.team.name,
                    "organization_id": canvas.team.organization_id,
                    "organization_name": canvas.team.organization.name,
                    "url": canvas_url(canvas),
                }
            ).data
        )
