"""DRF views for cross_project_dashboards. They read the request, call the facade and serialize the result."""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.pagination import FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission, get_authenticator_scoped_team_ids

from ..facade import api, contracts
from .serializers import (
    CrossProjectDashboardListItemSerializer,
    CrossProjectDashboardSerializer,
    CrossProjectDashboardTileSerializer,
    CrossProjectDashboardTileUpdateSerializer,
)

CHANGE_DENIED = "This dashboard has tiles from a project you cannot open, so you cannot change or delete it."
DASHBOARD_ID = PathParameter(type=UUID, description="Id of the dashboard.")


class CrossProjectDashboardPagination(FacadeLimitOffsetPagination):
    default_limit = 100
    max_limit = 100


class OrganizationWideCredentialPermission(BasePermission):
    """A dashboard spans the organization, so a credential confined to some projects cannot use it.

    The check reads the credential itself, because a capture token in the query string can give
    an organization route a project and pass the routing mixin's own scope check.
    """

    message = "This credential is limited to specific projects. Cross-project dashboards need organization-wide access."

    def has_permission(self, request: Request, view: Any) -> bool:
        return get_authenticator_scoped_team_ids(getattr(request, "successful_authenticator", None)) is None


class CrossProjectDashboardViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Dashboards the organization owns, holding insights from one or more projects."""

    # Any organization member may create one, and may edit or delete one whose tiles all come from
    # projects they can open. A dashboard holds only references, and each reader's own project
    # access decides what every tile shows.
    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardSerializer
    lookup_field = "id"
    path_parameters = {"id": DASHBOARD_ID}
    pagination_class = CrossProjectDashboardPagination
    # Server-side rollout boundary: the flag gates the API, not only the UI.
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission, OrganizationWideCredentialPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return self.kwargs["id"]

    @extend_schema(responses={200: CrossProjectDashboardListItemSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        return facade_page_response(
            self,
            lambda page: api.list_dashboards(organization_id=self.organization_id, user=self._user(), page=page),
            serializer_class=CrossProjectDashboardListItemSerializer,
        )

    @extend_schema(request=CrossProjectDashboardSerializer, responses={201: CrossProjectDashboardSerializer})
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = CrossProjectDashboardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dashboard = api.create_dashboard(
            organization_id=self.organization_id,
            user=self._user(),
            dashboard=contracts.NewDashboard(**serializer.validated_data),
        )
        return Response(CrossProjectDashboardSerializer(dashboard).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CrossProjectDashboardSerializer})
    def retrieve(self, request: Request, **kwargs: Any) -> Response:
        try:
            dashboard = api.get_dashboard(
                organization_id=self.organization_id, dashboard_id=self._object_id(), user=self._user()
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        return Response(CrossProjectDashboardSerializer(dashboard).data)

    @extend_schema(
        request=CrossProjectDashboardSerializer(partial=True),
        responses={200: CrossProjectDashboardSerializer},
    )
    def partial_update(self, request: Request, **kwargs: Any) -> Response:
        serializer = CrossProjectDashboardSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = contracts.DashboardChanges(fields=frozenset(serializer.validated_data), **serializer.validated_data)
        try:
            dashboard = api.update_dashboard(
                organization_id=self.organization_id, dashboard_id=self._object_id(), user=self._user(), changes=changes
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(CrossProjectDashboardSerializer(dashboard).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, **kwargs: Any) -> Response:
        try:
            api.delete_dashboard(
                organization_id=self.organization_id, dashboard_id=self._object_id(), user=self._user()
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CrossProjectDashboardTileViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Tiles on one cross-project dashboard, edited one at a time.

    Writes are per tile rather than a whole-set replace, so two people editing the same
    dashboard cannot overwrite each other's tiles.
    """

    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardTileSerializer
    lookup_field = "id"
    path_parameters = {
        "id": PathParameter(type=UUID, description="Id of the tile."),
        "dashboard_id": DASHBOARD_ID,
    }
    pagination_class = CrossProjectDashboardPagination
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission, OrganizationWideCredentialPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return self.kwargs["id"]

    def _dashboard_id(self) -> UUID:
        return self.kwargs["parent_lookup_dashboard_id"]

    @extend_schema(responses={200: CrossProjectDashboardTileSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        return facade_page_response(
            self,
            lambda page: api.list_tiles(
                organization_id=self.organization_id, dashboard_id=self._dashboard_id(), user=self._user(), page=page
            ),
        )

    @extend_schema(
        request=CrossProjectDashboardTileSerializer,
        responses={201: CrossProjectDashboardTileSerializer},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = CrossProjectDashboardTileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            tile = api.create_tile(
                organization_id=self.organization_id,
                dashboard_id=self._dashboard_id(),
                user=self._user(),
                tile=contracts.NewTile(**serializer.validated_data),
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(CrossProjectDashboardTileSerializer(tile).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: CrossProjectDashboardTileSerializer})
    def retrieve(self, request: Request, **kwargs: Any) -> Response:
        try:
            tile = api.get_tile(
                organization_id=self.organization_id,
                dashboard_id=self._dashboard_id(),
                tile_id=self._object_id(),
                user=self._user(),
            )
        except contracts.TileNotFoundError:
            raise NotFound()
        return Response(CrossProjectDashboardTileSerializer(tile).data)

    @extend_schema(
        request=CrossProjectDashboardTileUpdateSerializer(partial=True),
        responses={200: CrossProjectDashboardTileSerializer},
    )
    def partial_update(self, request: Request, **kwargs: Any) -> Response:
        serializer = CrossProjectDashboardTileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = contracts.TileChanges(fields=frozenset(serializer.validated_data), **serializer.validated_data)
        try:
            tile = api.update_tile(
                organization_id=self.organization_id,
                dashboard_id=self._dashboard_id(),
                tile_id=self._object_id(),
                user=self._user(),
                changes=changes,
            )
        except contracts.TileNotFoundError:
            raise NotFound()
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(CrossProjectDashboardTileSerializer(tile).data)

    @extend_schema(responses={204: None})
    def destroy(self, request: Request, **kwargs: Any) -> Response:
        try:
            api.delete_tile(
                organization_id=self.organization_id,
                dashboard_id=self._dashboard_id(),
                tile_id=self._object_id(),
                user=self._user(),
            )
        except contracts.TileNotFoundError:
            raise NotFound()
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(status=status.HTTP_204_NO_CONTENT)
