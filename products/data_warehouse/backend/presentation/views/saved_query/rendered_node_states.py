"""DAG node state for the saved queries one serializer renders, read once per response."""

from rest_framework import serializers

from products.data_modeling.backend.facade.api import node_states_by_saved_query
from products.data_modeling.backend.facade.contracts import SavedQueryNodeState
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery


def rendered_node_states(
    root: serializers.BaseSerializer, view: DataWarehouseSavedQuery
) -> dict[str, SavedQueryNodeState]:
    """Node state for every view the root serializer renders, keyed by saved query id.

    Resolved from the root's instance rather than the viewset context, because the context is
    built without knowing which page of views is being serialized. Memoized on the root so a
    `list` response costs one query instead of one per view. Reading at render time, not through a
    prefetch, keeps an edit's response current.
    """
    cached = getattr(root, "_rendered_node_states_cache", None)
    if cached is not None:
        return cached

    instance = root.instance
    if isinstance(instance, DataWarehouseSavedQuery):
        views = [instance]
    elif instance is None:
        views = [view]
    else:
        views = list(instance)

    states = node_states_by_saved_query(view.team_id, [rendered.pk for rendered in views])
    root._rendered_node_states_cache = states  # type: ignore[attr-defined]
    return states
