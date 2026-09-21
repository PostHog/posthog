"""Which DAG nodes and edges a reader may see, object grant by object grant.

A node carries the name, the type and the dependency edges of the warehouse table, view, endpoint
or catalog metric behind it, so a reader denied one of those objects must not receive its node
either. These viewsets are `scope_object = "INTERNAL"`, which keeps `AccessControlPermission` off
them, so the object grants `Database` applies to a query are resolved here as well.
"""

from __future__ import annotations

from functools import cached_property, reduce
from operator import or_
from typing import TYPE_CHECKING

from django.db.models import Q, QuerySet
from django.db.models.functions import Lower

from posthog.hogql.database.database import DeniedWarehouseObjects, denied_warehouse_objects

from products.data_modeling.backend.facade.models import Edge, Node, NodeType

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import UserAccessControl

# Node.name is lowercased for the comparison, because a denied table's qualified name is itself
# lowercased while a dependency resolves through HogQL under whatever casing its author typed.
_LOWER_NAME = "_lower_name"


class NodeVisibilityMixin:
    """Keeps the nodes and edges of objects the reader may not read out of every response.

    The resource-level warehouse check decides whether a reader gets the DAG at all. Object grants
    decide which of its nodes they get.
    """

    user_access_control: UserAccessControl
    team_id: int

    def _metric_nodes_hidden(self) -> bool:
        return not self.user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer")

    @cached_property
    def _denied_warehouse_objects(self) -> DeniedWarehouseObjects:
        return denied_warehouse_objects(self.team_id, self.user_access_control)

    @cached_property
    def _hidden_nodes(self) -> QuerySet[Node] | None:
        """This team's nodes the reader may not see, or None when nothing is hidden.

        A queryset rather than a set of ids, so the common case, a reader denied nothing, costs
        no query at all.
        """
        denied = self._denied_warehouse_objects
        metric_nodes_hidden = self._metric_nodes_hidden()

        clauses: list[Q] = []
        nodes = Node.objects.filter(team_id=self.team_id)

        if metric_nodes_hidden:
            clauses.append(Q(type=NodeType.METRIC))
        if denied.saved_query_ids:
            clauses.append(Q(saved_query_id__in=sorted(denied.saved_query_ids)))
        if denied.table_ids:
            # The sync writes this id on the nodes it creates; older table nodes carry no id and
            # match by name instead.
            clauses.append(Q(properties__warehouse_table_id__in=sorted(denied.table_ids)))
        if denied.names:
            nodes = nodes.annotate(**{_LOWER_NAME: Lower("name")})
            clauses.append(
                Q(type=NodeType.TABLE, **{f"{_LOWER_NAME}__in": sorted(name.lower() for name in denied.names)})
            )

        if not clauses:
            return None

        hidden = reduce(or_, clauses)
        if not metric_nodes_hidden:
            # A metric's node has one incoming edge per table and view its definition reads, so a
            # metric reading a denied object goes too. This is the rule the metrics API applies
            # to `referenced_table_names`.
            hidden = hidden | Q(
                type=NodeType.METRIC,
                id__in=Edge.objects.filter(team_id=self.team_id, source__in=nodes.filter(hidden)).values("target_id"),
            )
        return nodes.filter(hidden)

    @cached_property
    def _hidden_node_ids(self) -> frozenset[str]:
        """The hidden node ids, for the traversals and the counts that run in memory."""
        if self._hidden_nodes is None:
            return frozenset()
        return frozenset(str(node_id) for node_id in self._hidden_nodes.values_list("id", flat=True))

    def _exclude_hidden_nodes(self, queryset: QuerySet) -> QuerySet:
        if self._hidden_nodes is None:
            return queryset
        return queryset.exclude(id__in=self._hidden_nodes.values("id"))

    def _exclude_hidden_edges(self, queryset: QuerySet) -> QuerySet:
        """Drop every edge touching a hidden node, so the graph never says a hidden node is there."""
        if self._hidden_nodes is None:
            return queryset
        hidden_ids = self._hidden_nodes.values("id")
        return queryset.exclude(Q(source_id__in=hidden_ids) | Q(target_id__in=hidden_ids))
