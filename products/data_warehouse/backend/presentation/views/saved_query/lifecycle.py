"""Deleting a saved query: its DAG node, its joins, and its materialized table."""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.contracts import Dependent

if TYPE_CHECKING:
    from products.data_modeling.backend.facade.api import HasDependentsError


def _readable_saved_query_ids(
    dependents: Sequence[Dependent], user_access_control: UserAccessControl
) -> frozenset[str]:
    objects = [
        (dependent.saved_query_id, dependent.created_by_id)
        for dependent in dependents
        if dependent.saved_query_id is not None
    ]
    if not objects:
        return frozenset()
    levels = user_access_control.bulk_object_access_levels("warehouse_view", objects)
    return frozenset(
        saved_query_id for saved_query_id, level in levels.items() if level is not None and level != "none"
    )


def _metrics_readable(dependents: Sequence[Dependent], user_access_control: UserAccessControl) -> bool:
    if not any(dependent.saved_query_id is None for dependent in dependents):
        return False
    return user_access_control.check_access_level_for_resource("data_catalog", required_level="viewer")


def visible_dependents(
    dependents: Sequence[Dependent], user_access_control: UserAccessControl | None
) -> list[Dependent]:
    """The dependents this caller may be told the name of. Fails closed when there is no access control.

    A saved query is resolved through its own `warehouse_view` object grant, one bulk call for all of
    them. A metric is all or nothing on project `data_catalog` viewer, the gate the metric API uses.
    """
    if user_access_control is None:
        return []
    readable_saved_queries = _readable_saved_query_ids(dependents, user_access_control)
    metrics_readable = _metrics_readable(dependents, user_access_control)
    return [
        dependent
        for dependent in dependents
        if dependent.saved_query_id in readable_saved_queries or (dependent.saved_query_id is None and metrics_readable)
    ]


def refusal_node_id(
    error: "HasDependentsError",
    visible: Sequence[Dependent],
    user_access_control: UserAccessControl | None,
) -> str | None:
    """The node the refused delete may link to, or None when the caller could not open it anyway.

    NodeViewSet re-applies resource-level `warehouse_view` viewer by hand, so a caller holding only
    an object grant would get a button that 403s.
    """
    from products.data_modeling.backend.facade.api import blocked_lineage_node_id

    if user_access_control is None:
        return None
    if not user_access_control.check_access_level_for_resource("warehouse_view", required_level="viewer"):
        return None
    return blocked_lineage_node_id(visible, error.fallback_node_id)
