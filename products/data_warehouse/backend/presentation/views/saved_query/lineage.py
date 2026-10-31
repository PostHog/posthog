"""Walking a saved query's ancestors and descendants through the data modeling DAG."""

from typing import cast

from django.db.models import Model

from rest_framework import request, serializers

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.api import reachable_node_ids, saved_query_node_ids
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Node, NodeType
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class SavedQueryLineageRequestSerializer(serializers.Serializer):
    """Body of the `ancestors` and `descendants` actions."""

    level = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=1,
        help_text="How many hops to walk, so 1 gives the immediate neighbours. Omit to walk the whole cone.",
    )


class SavedQueryAncestorsSerializer(serializers.Serializer):
    ancestors = serializers.ListField(
        child=serializers.CharField(),
        help_text="Ids of the saved queries and warehouse tables this query reads from, directly or "
        "through other queries, and the names of the PostHog tables among them.",
    )


class SavedQueryDescendantsSerializer(serializers.Serializer):
    descendants = serializers.ListField(
        child=serializers.CharField(),
        help_text="Ids of the saved queries that read from this query, directly or through other queries.",
    )


class SavedQueryDependenciesSerializer(serializers.Serializer):
    upstream_count = serializers.IntegerField(help_text="How many tables and queries this query reads from directly.")
    downstream_count = serializers.IntegerField(help_text="How many queries read from this query directly.")


def _parse_level(request: request.Request) -> int | None:
    """Read the `level` bound off a lineage request.

    No level means walk the whole cone. Zero or less would walk nothing and return an empty
    answer, so it is refused, as is anything that is not a whole number.
    """
    serializer = SavedQueryLineageRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data.get("level")


def _related_saved_queries(
    saved_query: DataWarehouseSavedQuery,
    user_access_control: UserAccessControl,
    *,
    upstream: bool,
    max_depth: int | None,
) -> set[str]:
    """Walk the data modeling graph from a saved query and identify what it reaches.

    The walk starts from every node that stands for the query and unions what they reach.

    Each reached node is identified the way the lineage endpoints have always identified it: a
    query by its saved-query id, an imported warehouse table by its `DataWarehouseTable` id, and a
    PostHog system table by its name. A table node carries the id in its properties
    (`saved_query_dag_sync.resolve_dependency_to_node`) rather than the `saved_query` FK.
    """
    start_node_ids = saved_query_node_ids(saved_query.team_id, saved_query.id)
    if not start_node_ids:
        return set()

    reached = reachable_node_ids(saved_query.team_id, start_node_ids, upstream=upstream, max_depth=max_depth)

    visible_identifiers: set[str] = set()
    saved_query_ids: set[str] = set()
    warehouse_table_ids: set[str] = set()
    for node_type, saved_query_id, name, properties in Node.objects.filter(
        team=saved_query.team, id__in=reached
    ).values_list("type", "saved_query_id", "name", "properties"):
        properties = properties or {}
        if node_type == NodeType.METRIC:
            continue
        if properties.get("origin") == "posthog":
            visible_identifiers.add(name)
        elif saved_query_id is not None:
            saved_query_ids.add(str(saved_query_id))
        elif properties.get("warehouse_table_id"):
            warehouse_table_ids.add(str(properties["warehouse_table_id"]))

    if saved_query_ids:
        creators = DataWarehouseSavedQuery.objects.filter(
            id__in=saved_query_ids, team_id=saved_query.team_id
        ).values_list("id", "created_by_id")
        levels = user_access_control.bulk_object_access_levels(
            "warehouse_view", [(str(saved_query_id), created_by_id) for saved_query_id, created_by_id in creators]
        )
        visible_identifiers.update(
            saved_query_id for saved_query_id, level in levels.items() if level is not None and level != "none"
        )

    if warehouse_table_ids:
        tables = list(
            DataWarehouseTable.objects.filter(id__in=warehouse_table_ids, team_id=saved_query.team_id).exclude(
                deleted=True
            )
        )
        user_access_control.preload_object_access_controls(cast(list[Model], tables))
        visible_identifiers.update(
            str(table.id) for table in tables if user_access_control.check_access_level_for_object(table, "viewer")
        )

    return visible_identifiers
