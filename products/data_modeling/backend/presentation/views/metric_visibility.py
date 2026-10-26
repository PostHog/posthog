from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from rest_framework.exceptions import PermissionDenied

from products.data_modeling.backend.facade.flags import is_managed_viewset_enabled
from products.data_modeling.backend.facade.models import NodeType

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl

DELETE_DENIED = "Deleting data models requires data warehouse write access."


class MetricNodeVisibilityMixin:
    user_access_control: "UserAccessControl"
    team: "Team"

    def _require_warehouse_access(self, *, level: "AccessControlLevel", message: str) -> None:
        """`scope_object = "INTERNAL"` makes AccessControlPermission skip this viewset entirely, so
        warehouse RBAC has to be re-applied by hand (warehouse_view inherits warehouse_objects)."""
        if not self.user_access_control.check_access_level_for_resource("warehouse_view", required_level=level):
            raise PermissionDenied(message)

    def _metric_nodes_hidden(self) -> bool:
        return not self.user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer")

    def _hidden_node_types(self) -> frozenset[str]:
        return frozenset({NodeType.METRIC}) if self._metric_nodes_hidden() else frozenset()

    def _managed_views_hidden(self) -> bool:
        return not is_managed_viewset_enabled(self.team)

    def _exclude_hidden_nodes(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.exclude(saved_query__deleted=True)
        if self._managed_views_hidden():
            queryset = queryset.exclude(saved_query__managed_viewset__isnull=False)
        if self._metric_nodes_hidden():
            return queryset.exclude(type=NodeType.METRIC)
        return queryset

    def _exclude_hidden_edges(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.exclude(Q(source__saved_query__deleted=True) | Q(target__saved_query__deleted=True))
        if self._managed_views_hidden():
            queryset = queryset.exclude(
                Q(source__saved_query__managed_viewset__isnull=False)
                | Q(target__saved_query__managed_viewset__isnull=False)
            )
        if self._metric_nodes_hidden():
            return queryset.exclude(Q(source__type=NodeType.METRIC) | Q(target__type=NodeType.METRIC))
        return queryset
