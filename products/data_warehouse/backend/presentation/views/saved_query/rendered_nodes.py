"""DAG nodes behind the saved queries one serializer renders, read once per response."""

from rest_framework import serializers

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery, Node


def rendered_nodes(root: serializers.BaseSerializer, view: DataWarehouseSavedQuery) -> dict[str, list[Node]]:
    """Nodes for every view the root serializer renders, keyed by saved query id.

    Resolved from the root's instance rather than the viewset context, because the context is
    built without knowing which page of views is being serialized. Memoized on the root so a
    `list` response costs one query instead of one per view. Reading at render time, not through a
    prefetch, keeps an edit's response current.
    """
    cached = getattr(root, "_rendered_nodes_cache", None)
    if cached is not None:
        return cached

    instance = root.instance
    if isinstance(instance, DataWarehouseSavedQuery):
        views = [instance]
    elif instance is None:
        views = [view]
    else:
        views = list(instance)

    nodes: dict[str, list[Node]] = {}
    for node in Node.objects.filter(team_id=view.team_id, saved_query_id__in=[rendered.pk for rendered in views]).only(
        "saved_query_id", "properties"
    ):
        nodes.setdefault(str(node.saved_query_id), []).append(node)
    root._rendered_nodes_cache = nodes  # type: ignore[attr-defined]
    return nodes
