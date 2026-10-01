"""DRF views for cross_project_dashboards."""

from typing import Any

from django.db.models import Prefetch, QuerySet
from django.shortcuts import get_object_or_404

from rest_framework import viewsets
from rest_framework.serializers import BaseSerializer

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import PostHogFeatureFlagPermission

from products.cross_project_dashboards.backend.facade.api import CrossProjectDashboard, CrossProjectDashboardTile
from products.cross_project_dashboards.backend.presentation.serializers import (
    CrossProjectDashboardSerializer,
    CrossProjectDashboardTileSerializer,
)


class CrossProjectDashboardViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Dashboards the organization owns, holding insights from one or more projects."""

    # Any organization member may create, edit and delete these by design: a dashboard holds only
    # references, and each reader's own project access decides what every tile shows.
    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardSerializer
    queryset = CrossProjectDashboard.objects.all()
    lookup_field = "id"
    # Server-side rollout boundary: the flag gates the API, not only the UI.
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return (
            queryset.filter(organization_id=self.organization_id, deleted=False)
            .prefetch_related(
                Prefetch(
                    "tiles",
                    queryset=CrossProjectDashboardTile.objects.filter(deleted=False).order_by("created_at"),
                )
            )
            .order_by("-created_at")
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "organization_id": self.organization_id}

    def perform_destroy(self, instance: CrossProjectDashboard) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted"])


class CrossProjectDashboardTileViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Tiles on one cross-project dashboard, edited one at a time.

    Writes are per tile rather than a whole-set replace, so two people editing the same
    dashboard cannot overwrite each other's tiles.
    """

    scope_object = "cross_project_dashboard"
    serializer_class = CrossProjectDashboardTileSerializer
    queryset = CrossProjectDashboardTile.objects.all()
    lookup_field = "id"
    posthog_feature_flag = "cross-project-dashboards"
    permission_classes = [PostHogFeatureFlagPermission]

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        return queryset.filter(deleted=False, dashboard__deleted=False).order_by("created_at")

    def perform_create(self, serializer: BaseSerializer) -> None:
        dashboard = get_object_or_404(
            CrossProjectDashboard,
            id=self.parents_query_dict["dashboard_id"],
            organization_id=self.organization_id,
            deleted=False,
        )
        serializer.save(dashboard=dashboard, organization_id=dashboard.organization_id)

    def perform_destroy(self, instance: CrossProjectDashboardTile) -> None:
        instance.deleted = True
        instance.save(update_fields=["deleted"])
