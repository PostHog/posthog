from functools import cached_property
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet

from products.data_modeling.backend.facade.api import insight_node_ids
from products.data_modeling.backend.facade.models import NodeType
from products.product_analytics.backend.facade.api import insight_references

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl


class NodeVisibilityMixin:
    """Hides the nodes whose names the reader may not see, from node lists, edge lists and counts alike.

    A metric is all or nothing on project `data_catalog` viewer. An insight is resolved through its own
    `insight` object grant, and a node whose insight is deleted is hidden too, because nothing would
    open behind it.
    """

    team_id: int
    user_access_control: "UserAccessControl"

    def _hidden_node_types(self) -> frozenset[str]:
        if self.user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer"):
            return frozenset()
        return frozenset({NodeType.METRIC})

    @cached_property
    def _hidden_node_ids(self) -> frozenset[str]:
        node_id_by_insight = insight_node_ids(self.team_id)
        if not node_id_by_insight:
            return frozenset()
        references = insight_references(team_id=self.team_id, insight_ids=list(node_id_by_insight))
        levels = self.user_access_control.bulk_object_access_levels(
            "insight", [(str(reference.id), reference.created_by_id) for reference in references]
        )
        readable = {int(insight_id) for insight_id, level in levels.items() if level is not None and level != "none"}
        return frozenset(node_id for insight_id, node_id in node_id_by_insight.items() if insight_id not in readable)

    def _exclude_hidden_nodes(self, queryset: QuerySet) -> QuerySet:
        hidden_types = self._hidden_node_types()
        if hidden_types:
            queryset = queryset.exclude(type__in=hidden_types)
        if self._hidden_node_ids:
            queryset = queryset.exclude(id__in=self._hidden_node_ids)
        return queryset

    def _exclude_hidden_edges(self, queryset: QuerySet) -> QuerySet:
        hidden_types = self._hidden_node_types()
        if hidden_types:
            queryset = queryset.exclude(Q(source__type__in=hidden_types) | Q(target__type__in=hidden_types))
        if self._hidden_node_ids:
            queryset = queryset.exclude(Q(source_id__in=self._hidden_node_ids) | Q(target_id__in=self._hidden_node_ids))
        return queryset
