"""Walking a saved query's ancestors and descendants through the data modeling DAG."""

from rest_framework import request, serializers

from products.data_modeling.backend.facade.api import reachable_node_ids, saved_query_node_ids
from products.data_modeling.backend.facade.models import READER_NODE_TYPES, DataWarehouseSavedQuery, Node


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


def _related_saved_queries(saved_query: DataWarehouseSavedQuery, *, upstream: bool, max_depth: int | None) -> set[str]:
    """Walk the data modeling graph from a saved query and identify what it reaches.

    The walk starts from every node that stands for the query and unions what they reach: a
    saved query can hold a node in more than one DAG, and a query in a managed DAG is also
    represented by a proxy table node in each DAG that reads from it. Without the proxies a
    consumer would report the managed query upstream while the managed query reported no
    consumer downstream.

    Each reached node is identified the way the lineage endpoints have always identified it: a
    query by its saved-query id, an imported warehouse table by its `DataWarehouseTable` id, a
    cross-DAG proxy by the id of the saved query it stands in for, and a PostHog system table by
    its name. A table node carries the id in its properties
    (`saved_query_dag_sync.resolve_dependency_to_node`) rather than the `saved_query` FK.
    """
    start_node_ids = saved_query_node_ids(saved_query.team_id, saved_query.id)
    if not start_node_ids:
        return set()

    reached = reachable_node_ids(saved_query.team_id, start_node_ids, upstream=upstream, max_depth=max_depth)

    identifiers: set[str] = set()
    for node_type, saved_query_id, name, properties in Node.objects.filter(
        team=saved_query.team, id__in=reached
    ).values_list("type", "saved_query_id", "name", "properties"):
        properties = properties or {}
        if node_type in READER_NODE_TYPES:
            continue
        if saved_query_id is not None:
            identifiers.add(str(saved_query_id))
        elif properties.get("saved_query_id"):
            identifiers.add(str(properties["saved_query_id"]))
        elif properties.get("warehouse_table_id"):
            identifiers.add(str(properties["warehouse_table_id"]))
        else:
            identifiers.add(name)
    return identifiers
