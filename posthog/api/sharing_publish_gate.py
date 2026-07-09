"""Publish-time access gate for public sharing.

Shared links execute without warehouse access control (the publish act is the access
decision - see SharedLinkUser), so the gate moves to the moment of publishing: the member
enabling a share must be able to run every query it exposes. Otherwise sharing would be an
escalation channel - save a query over a restricted table, publish, read it through the
public link.
"""

import re
from typing import TYPE_CHECKING, Any, Optional

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.hogql_queries.query_runner import get_query_runner_or_none

from products.notebooks.backend.facade.content import extract_inline_query_nodes
from products.product_analytics.backend.models.insight import Insight

if TYPE_CHECKING:
    from posthog.models import Team, User
    from posthog.models.sharing_configuration import SharingConfiguration

# Must match the denial raised in posthog/hogql/database/database.py `get_table`.
_ACCESS_DENIED_TABLE = re.compile(r"You don't have access to table `([^`]+)`")


def tables_blocked_for_publisher(user: "User", team: "Team", config: "SharingConfiguration") -> list[str]:
    """Tables that stop the publisher from running the shared artifact's queries.

    Each query is compiled (resolved, not executed) under the publisher's own identity - the
    same resolution the read path uses - so the gate can't drift from HogQL: whatever a new
    query kind resolves, it resolves here too. The invariant is "you can publish exactly what
    you can run": a granted materialized view resolves to its backing table and publishes; a
    non-materialized view re-resolves through its underlying tables, so a denied table inside
    it blocks publishing just like it blocks the publisher's own in-app run.

    Non-access compile errors are skipped - a broken query fails for everyone at view time,
    which is not an access problem. Empty list = safe to publish.
    """
    queries = _queries_exposed_by(config)
    if not queries:
        return []

    # One context for all queries: the publisher's schema is built on first prepare and reused.
    context = HogQLContext(
        team_id=team.pk,
        team=team,
        user=user,
        enable_select_queries=True,
        modifiers=create_default_modifiers_for_user(user, team),
    )
    blocked: set[str] = set()
    for query in queries:
        select = _select_ast_for(query, team, user)
        if select is None:
            continue
        try:
            prepare_ast_for_printing(select, context=context, dialect="clickhouse")
        except Exception as e:
            # Only access denials gate publishing; anything else is the query's own problem.
            denied = _ACCESS_DENIED_TABLE.search(str(e))
            if denied:
                blocked.add(denied.group(1))
    return sorted(blocked)


def _queries_exposed_by(config: "SharingConfiguration") -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    insight_ids = config.get_connected_insight_ids()
    if insight_ids:
        queries.extend(
            q
            for q in Insight.objects.filter(team_id=config.team_id, id__in=insight_ids).values_list("query", flat=True)
            if isinstance(q, dict)
        )
    if config.notebook:
        queries.extend(query for _node_id, query in extract_inline_query_nodes(config.notebook.content))
    return queries


def _select_ast_for(
    query: dict[str, Any], team: "Team", user: "User"
) -> Optional[ast.SelectQuery | ast.SelectSetQuery]:
    """The query's select AST via its own runner, unwrapping container nodes (DataTableNode,
    InsightVizNode) the same way process_query_model does. None when the query isn't
    runner-backed or can't build - not an access problem, so nothing to gate."""
    node: Any = query
    while isinstance(node, dict):
        try:
            runner = get_query_runner_or_none(node, team, user=user)
        except Exception:
            return None
        if runner is not None:
            try:
                return runner.to_query()
            except Exception:
                return None
        node = node.get("source")
    return None
