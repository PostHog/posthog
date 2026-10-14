"""Run a guest's query from a saved reference.

A guest never chooses the query that runs. The request names a saved insight or a notebook query node, and the
server loads that item's query. The guest may change the date range, property filters and variables, but not a
breakdown or a HogQL filter, because those can list values such as emails.
"""

from typing import Any

from rest_framework.exceptions import NotFound, PermissionDenied

from posthog.schema import QueryRequest

from posthog.authz import check_object_access
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.authz.backend.facade.enums import Action
from products.notebooks.backend.facade.api import get_notebook
from products.notebooks.backend.facade.content import extract_inline_query_nodes
from products.product_analytics.backend.facade.models import Insight

# Wrapper nodes that hold the runnable query in `source`. The query endpoint runs the source.
_WRAPPER_KINDS = frozenset({"InsightVizNode", "DataTableNode", "DataVisualizationNode"})


@frozen
class GuestQuery:
    query: dict[str, Any]
    insight_id: int | None


def _check_overrides(request_data: QueryRequest) -> None:
    filters = request_data.filters_override
    if filters is None:
        return
    if filters.breakdown_filter is not None:
        raise PermissionDenied("Guests can't change a breakdown.")
    for item in filters.properties or []:
        if getattr(item, "type", None) == "hogql":
            raise PermissionDenied("Guests can't filter with HogQL expressions.")


def _runnable(query: dict[str, Any]) -> dict[str, Any]:
    source = query.get("source")
    return source if query.get("kind") in _WRAPPER_KINDS and isinstance(source, dict) else query


def _insight_query(team: Team, user: User, insight_id: int) -> GuestQuery:
    insight = Insight.objects.filter(team_id=team.pk, id=insight_id, deleted=False).first()
    if insight is None or not isinstance(insight.query, dict):
        raise NotFound()
    if not check_object_access(user, insight, Action.VIEW):
        raise PermissionDenied()
    return GuestQuery(query=_runnable(insight.query), insight_id=insight.id)


def _notebook_query(team: Team, user: User, short_id: str, node_id: str) -> GuestQuery:
    notebook = get_notebook(team.pk, short_id)
    if notebook is None:
        raise NotFound()
    reference = ObjectAccessRef(
        resource="notebook", id=str(notebook.id), team_id=team.pk, created_by_id=notebook.created_by_id
    )
    if not check_object_access(user, reference, Action.VIEW):
        raise PermissionDenied()
    query = next((query for id, query in extract_inline_query_nodes(notebook.content) if id == node_id), None)
    if query is None:
        raise NotFound()
    return GuestQuery(query=_runnable(query), insight_id=None)


def resolve_guest_query(request_data: QueryRequest, team: Team, user: User) -> GuestQuery:
    _check_overrides(request_data)
    if request_data.insight_id is not None:
        return _insight_query(team, user, request_data.insight_id)
    if request_data.notebook_short_id is not None and request_data.node_id is not None:
        return _notebook_query(team, user, request_data.notebook_short_id, request_data.node_id)
    raise PermissionDenied("Guests can only run the queries of the items shared with them.")
