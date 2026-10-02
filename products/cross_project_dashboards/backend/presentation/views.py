"""DRF views for cross_project_dashboards. They read the request, call the facade and serialize the result."""

from typing import Any, cast
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
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


class CrossProjectDashboardPagination(LimitOffsetPagination):
    # The shared paginator has no ceiling, so ?limit= could ask a single request for every row.
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


class _FacadePageMixin:
    def _paginated(self, request: Request, page: contracts.DashboardPage | contracts.TilePage, data: Any) -> Response:
        paginator = self.paginator  # type: ignore[attr-defined]
        paginator.request = request
        paginator.limit = paginator.get_limit(request)
        paginator.offset = paginator.get_offset(request)
        paginator.count = page.count
        return paginator.get_paginated_response(data)

    def _offset(self, request: Request) -> int:
        return self.paginator.get_offset(request)  # type: ignore[attr-defined]

    def _limit(self, request: Request) -> int:
        return self.paginator.get_limit(request)  # type: ignore[attr-defined]


class CrossProjectDashboardViewSet(TeamAndOrgViewSetMixin, _FacadePageMixin, viewsets.GenericViewSet):
    """Dashboards the organization owns, holding insights from one or more projects."""

    # Any organization member may create one, and may edit or delete one whose tiles all come from
    # projects they can open. A dashboard holds only references, and each reader's own project
    # access decides what every tile shows.
    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardSerializer
    lookup_field = "id"
    pagination_class = CrossProjectDashboardPagination
    # Server-side rollout boundary: the flag gates the API, not only the UI.
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission, OrganizationWideCredentialPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return _uuid(self.kwargs["id"])

    @extend_schema(responses={200: CrossProjectDashboardListItemSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        page = api.list_dashboards(
            organization_id=self.organization_id,
            user=self._user(),
            offset=self._offset(request),
            limit=self._limit(request),
        )
        return self._paginated(request, page, CrossProjectDashboardListItemSerializer(page.results, many=True).data)

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
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(CrossProjectDashboardSerializer(dashboard).data)

    @extend_schema(parameters=[DASHBOARD_ID], responses={204: None})
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


class CrossProjectDashboardTileViewSet(TeamAndOrgViewSetMixin, _FacadePageMixin, viewsets.GenericViewSet):
    """Tiles on one cross-project dashboard, edited one at a time.

    Writes are per tile rather than a whole-set replace, so two people editing the same
    dashboard cannot overwrite each other's tiles.
    """

    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardTileSerializer
    lookup_field = "id"
    pagination_class = CrossProjectDashboardPagination
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission, OrganizationWideCredentialPermission]

    def _user(self) -> User:
        return cast(User, self.request.user)

    def _object_id(self) -> UUID:
        return _uuid(self.kwargs["id"])

    def _dashboard_id(self) -> UUID:
        return _uuid(self.parents_query_dict["dashboard_id"])

    @extend_schema(parameters=[PARENT_DASHBOARD_ID], responses={200: CrossProjectDashboardTileSerializer(many=True)})
    def list(self, request: Request, **kwargs: Any) -> Response:
        page = api.list_tiles(
            organization_id=self.organization_id,
            dashboard_id=self._dashboard_id(),
            user=self._user(),
            offset=self._offset(request),
            limit=self._limit(request),
        )
        return self._paginated(request, page, CrossProjectDashboardTileSerializer(page.results, many=True).data)

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
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
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
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
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
        except contracts.DashboardChangeDeniedError:
            raise PermissionDenied(CHANGE_DENIED)
        return Response(status=status.HTTP_204_NO_CONTENT)
