from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from products.data_modeling.backend.facade.models import NodeType

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class MetricNodeVisibilityMixin:
    user_access_control: "UserAccessControl"

    def _metric_nodes_hidden(self) -> bool:
        return not self.user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer")

    def _hidden_node_types(self) -> frozenset[str]:
        return frozenset({NodeType.METRIC}) if self._metric_nodes_hidden() else frozenset()

    def _exclude_hidden_nodes(self, queryset: QuerySet) -> QuerySet:
        if self._metric_nodes_hidden():
            return queryset.exclude(type=NodeType.METRIC)
        return queryset

    def _exclude_hidden_edges(self, queryset: QuerySet) -> QuerySet:
        if self._metric_nodes_hidden():
            return queryset.exclude(Q(source__type=NodeType.METRIC) | Q(target__type=NodeType.METRIC))
        return queryset
