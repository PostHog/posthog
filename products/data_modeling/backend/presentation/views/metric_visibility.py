from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q, QuerySet

from rest_framework.exceptions import PermissionDenied

from products.data_modeling.backend.facade.flags import is_managed_viewset_enabled
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, NodeType
from products.warehouse_sources.backend.facade.api import allowed_table_ids

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
    from products.data_modeling.backend.facade.api import SavedQueryFrequencyBounds

DELETE_DENIED = "Deleting data models requires data warehouse write access."
EDIT_DENIED = "Editing data models requires data warehouse write access."
VIEW_EDIT_DENIED = "You need edit access to this view."


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


class MetricNodeVisibilityMixin:
    user_access_control: "UserAccessControl"
    team: "Team"

    def _require_warehouse_access(self, *, level: "AccessControlLevel", message: str) -> None:
        """`scope_object = "INTERNAL"` makes AccessControlPermission skip this viewset entirely, so
        warehouse RBAC has to be re-applied by hand (warehouse_view inherits warehouse_objects)."""
        if not self.user_access_control.check_access_level_for_resource("warehouse_view", required_level=level):
            raise PermissionDenied(message)

    def _require_view_edit_access(self, *saved_queries: "DataWarehouseSavedQuery | None") -> None:
        """The resource check above passes a member who holds a deny rule on one view, so a write to a
        node or edge of that view also checks the view itself."""
        for saved_query in saved_queries:
            if saved_query is not None and not self.user_access_control.check_access_level_for_object(
                saved_query, "editor"
            ):
                raise PermissionDenied(VIEW_EDIT_DENIED)

    def _readable_node_names(self, resolved: "SavedQueryFrequencyBounds") -> dict[str, str]:
        """The names in a lineage this caller may read, keyed by node id.

        Fails closed and withholds the node id along with the name, as the saved-query surfaces do: a
        view under a `none` grant must not be named, or counted, by the cadence of a view beside it. A
        node that resolves to no resource (one that predates the origin stamp) is withheld too.
        """
        team_id = self.team.pk
        visible: dict[str, str] = {}
        node_ids_by_saved_query: dict[str, list[str]] = {}
        node_ids_by_table: dict[str, list[str]] = {}
        for node_id, identity in resolved.identities.items():
            if node_id not in resolved.names:
                continue
            if identity.is_posthog_table:
                visible[node_id] = resolved.names[node_id]  # events, persons and friends: readable by anyone
            elif identity.saved_query_id is not None:
                node_ids_by_saved_query.setdefault(identity.saved_query_id, []).append(node_id)
            elif identity.warehouse_table_id is not None:
                node_ids_by_table.setdefault(identity.warehouse_table_id, []).append(node_id)

        def reveal(node_ids: list[str]) -> None:
            visible.update({node_id: resolved.names[node_id] for node_id in node_ids})

        if node_ids_by_saved_query:
            creators = DataWarehouseSavedQuery.objects.filter(
                id__in=node_ids_by_saved_query, team_id=team_id
            ).values_list("id", "created_by_id")
            levels = self.user_access_control.bulk_object_access_levels(
                "warehouse_view", [(str(pk), created_by) for pk, created_by in creators]
            )
            for saved_query_id, level in levels.items():
                if level is not None and level != "none":
                    reveal(node_ids_by_saved_query[saved_query_id])

        table_ids = [table_id for raw in node_ids_by_table if (table_id := _as_uuid(raw)) is not None]
        for table_id in allowed_table_ids(team_id, self.user_access_control, ids=table_ids):
            reveal(node_ids_by_table[str(table_id)])
        return visible

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
