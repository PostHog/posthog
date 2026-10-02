"""DRF views for cross_project_dashboards. They read the request, call the facade and serialize the result."""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.permissions import PostHogFeatureFlagPermission

from ..facade import api, contracts
from .serializers import (
    CrossProjectDashboardSerializer,
    CrossProjectDashboardTileSerializer,
    CrossProjectDashboardTileUpdateSerializer,
)

DASHBOARD_ID = OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Id of the dashboard.")
PARENT_DASHBOARD_ID = OpenApiParameter(
    "dashboard_id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Id of the dashboard."
)
TILE_ID = OpenApiParameter("id", OpenApiTypes.UUID, OpenApiParameter.PATH, description="Id of the tile.")


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise NotFound()


class CrossProjectDashboardViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Dashboards the organization owns, holding insights from one or more projects."""

    # Any organization member may create, edit and delete these by design: a dashboard holds only
    # references, and each reader's own project access decides what every tile shows.
    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardSerializer
    lookup_field = "id"
    # Server-side rollout boundary: the flag gates the API, not only the UI.
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return _uuid(self.kwargs["id"])

    @extend_schema(responses={200: CrossProjectDashboardSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        dashboards = api.list_dashboards(organization_id=self.organization_id, user=self._user())
        page = self.paginate_queryset(dashboards)
        if page is not None:
            return self.get_paginated_response(CrossProjectDashboardSerializer(page, many=True).data)
        return Response(CrossProjectDashboardSerializer(dashboards, many=True).data)

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

    @extend_schema(parameters=[DASHBOARD_ID], responses={200: CrossProjectDashboardSerializer})
    def retrieve(self, request: Request, **kwargs: Any) -> Response:
        try:
            dashboard = api.get_dashboard(
                organization_id=self.organization_id, dashboard_id=self._object_id(), user=self._user()
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        return Response(CrossProjectDashboardSerializer(dashboard).data)

    @extend_schema(
        parameters=[DASHBOARD_ID],
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
        return Response(CrossProjectDashboardSerializer(dashboard).data)

    @extend_schema(parameters=[DASHBOARD_ID], responses={204: None})
    def destroy(self, request: Request, **kwargs: Any) -> Response:
        try:
            api.delete_dashboard(
                organization_id=self.organization_id, dashboard_id=self._object_id(), user=self._user()
            )
        except contracts.DashboardNotFoundError:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CrossProjectDashboardTileViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Tiles on one cross-project dashboard, edited one at a time.

    Writes are per tile rather than a whole-set replace, so two people editing the same
    dashboard cannot overwrite each other's tiles.
    """

    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardTileSerializer
    lookup_field = "id"
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return _uuid(self.kwargs["id"])

    def _dashboard_id(self) -> UUID:
        return _uuid(self.parents_query_dict["dashboard_id"])

    @extend_schema(parameters=[PARENT_DASHBOARD_ID], responses={200: CrossProjectDashboardTileSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        tiles = api.list_tiles(
            organization_id=self.organization_id, dashboard_id=self._dashboard_id(), user=self._user()
        )
        page = self.paginate_queryset(tiles)
        if page is not None:
            return self.get_paginated_response(CrossProjectDashboardTileSerializer(page, many=True).data)
        return Response(CrossProjectDashboardTileSerializer(tiles, many=True).data)

    @extend_schema(
        parameters=[PARENT_DASHBOARD_ID],
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
        return Response(CrossProjectDashboardTileSerializer(tile).data, status=status.HTTP_201_CREATED)

    @extend_schema(parameters=[PARENT_DASHBOARD_ID, TILE_ID], responses={200: CrossProjectDashboardTileSerializer})
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
        parameters=[PARENT_DASHBOARD_ID, TILE_ID],
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
        return Response(CrossProjectDashboardTileSerializer(tile).data)

    @extend_schema(parameters=[PARENT_DASHBOARD_ID, TILE_ID], responses={204: None})
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
        return Response(status=status.HTTP_204_NO_CONTENT)
