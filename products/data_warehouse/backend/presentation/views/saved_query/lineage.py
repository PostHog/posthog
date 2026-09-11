"""Saved-query lineage traversal helpers."""

from django.db.models import Q

from rest_framework import request

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Edge, Node

from . import schemas


def _parse_level(request: request.Request) -> int | None:
    """Read the `level` bound off a lineage request.

    No level means walk the whole cone. Zero or less would walk nothing and return an empty
    answer, so it is refused, as is anything that is not a whole number.
    """
    serializer = schemas.SavedQueryLineageRequestSerializer(data=request.data)
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
    start_node_ids = {
        str(node_id)
        for node_id in Node.objects.filter(team=saved_query.team)
        .filter(Q(saved_query=saved_query) | Q(properties__saved_query_id=str(saved_query.id)))
        .values_list("id", flat=True)
    }
    if not start_node_ids:
        return set()

    reached = _reachable_node_ids(saved_query.team_id, start_node_ids, upstream=upstream, max_depth=max_depth)

    identifiers: set[str] = set()
    for saved_query_id, name, properties in Node.objects.filter(team=saved_query.team, id__in=reached).values_list(
        "saved_query_id", "name", "properties"
    ):
        properties = properties or {}
        if saved_query_id is not None:
            identifiers.add(str(saved_query_id))
        elif properties.get("saved_query_id"):
            identifiers.add(str(properties["saved_query_id"]))
        elif properties.get("warehouse_table_id"):
            identifiers.add(str(properties["warehouse_table_id"]))
        else:
            identifiers.add(name)
    return identifiers


def _reachable_node_ids(team_id: int, start_node_ids: set[str], *, upstream: bool, max_depth: int | None) -> set[str]:
    """Node ids reachable from `start_node_ids` within `max_depth` hops, the start nodes excluded.

    One query per hop, each reading the frontier's edges off the `Edge` foreign-key indexes, so
    the work is bounded by the cone that is reached rather than by every edge the team owns.
    Upstream follows edges into the frontier back to their sources; downstream follows edges
    out of it to their targets.
    """
    edges = Edge.objects.filter(team_id=team_id)

    reached: set[str] = set()
    frontier = set(start_node_ids)
    depth = 0
    while frontier and (max_depth is None or depth < max_depth):
        if upstream:
            neighbor_ids = edges.filter(target_id__in=frontier).values_list("source_id", flat=True)
        else:
            neighbor_ids = edges.filter(source_id__in=frontier).values_list("target_id", flat=True)
        frontier = {str(neighbor_id) for neighbor_id in neighbor_ids} - reached - start_node_ids
        reached |= frontier
        depth += 1
    return reached
