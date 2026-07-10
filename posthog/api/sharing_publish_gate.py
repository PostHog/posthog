"""Publish-time access gate for public sharing.

Shared links execute without warehouse access control (the publish act is the access
decision - see SharedLinkUser), so the gate moves to the moment of publishing: the member
enabling a share must be able to run every query it exposes. Otherwise sharing would be an
escalation channel - save a query over a restricted table, publish, read it through the
public link.
"""

from typing import Any

from django.db.models import Q

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import TableAccessDeniedError
from posthog.hogql.modifiers import create_default_modifiers_for_user
from posthog.hogql.printer import prepare_ast_for_printing

from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.models import Team, User
from posthog.models.sharing_configuration import SharingConfiguration

from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.facade.content import extract_inline_query_nodes, extract_referenced_insight_short_ids
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.models.insight import Insight


def tables_blocked_for_publisher(user: User, team: Team, config: SharingConfiguration) -> list[str]:
    """
    Tables that stop the publisher from running the shared artifact's queries.
    Each query is compiled (resolved, not executed) as the publisher - the same resolution
    the read path uses. Non-access compile errors don't gate. Empty list = safe to publish.
    """
    return tables_blocked_for_user(user, team, _queries_exposed_by(config))


def tables_blocked_for_user(user: User, team: Team, queries: list[dict[str, Any]]) -> list[str]:
    """Tables the user can't access among everything the given queries read - the compile core
    shared by the publish gate and the save-time block on already-shared artifacts."""
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
        try:
            # get_query_runner unwraps container nodes (DataTableNode, InsightVizNode, ...) itself.
            runner = get_query_runner_or_none(query, team, user=user)
            if runner is None:
                continue
            prepare_ast_for_printing(runner.to_query(), context=context, dialect="clickhouse")
        except TableAccessDeniedError as e:
            blocked.add(e.table_name)
        except Exception:
            # Only access denials gate publishing; anything else is the query's own problem.
            continue
    return sorted(blocked)


def _queries_exposed_by(config: SharingConfiguration) -> list[dict[str, Any]]:
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


def is_publicly_shared(artifact: "Dashboard | Notebook | Insight") -> bool:
    """Whether an active share exposes the artifact. Dashboards and notebooks are covered by
    their own share; an insight also transitively - by a shared dashboard's tile or a shared
    notebook embedding it."""
    if isinstance(artifact, Insight):
        live_tile = Q(dashboard__tiles__insight=artifact) & (
            Q(dashboard__tiles__deleted__isnull=True) | Q(dashboard__tiles__deleted=False)
        )
        if SharingConfiguration.objects.filter(
            SharingConfiguration.tokens_active_q(), Q(insight=artifact) | live_tile
        ).exists():
            return True
        # Notebooks reference insights inside their content JSON, so the few active notebook
        # shares per team are scanned rather than joined.
        return any(
            artifact.short_id in extract_referenced_insight_short_ids(config.notebook.content)
            for config in SharingConfiguration.objects.filter(
                SharingConfiguration.tokens_active_q(), team_id=artifact.team_id, notebook__isnull=False
            ).select_related("notebook")
        )
    field = "dashboard" if isinstance(artifact, Dashboard) else "notebook"
    return SharingConfiguration.objects.filter(SharingConfiguration.tokens_active_q(), **{field: artifact}).exists()


def tables_blocked_in_notebook_edit(user: User, notebook: Any, new_content: dict[str, Any] | None) -> list[str]:
    """Only queries the edit adds or changes are checked,
    so untouched content (and anything mid-typing that doesn't resolve) never gates."""
    old_content = notebook.content or {}
    old_inline = dict(extract_inline_query_nodes(old_content))
    changed_queries = [
        query for node_id, query in extract_inline_query_nodes(new_content or {}) if old_inline.get(node_id) != query
    ]

    added_short_ids = set(extract_referenced_insight_short_ids(new_content or {})) - set(
        extract_referenced_insight_short_ids(old_content)
    )
    if added_short_ids:
        changed_queries.extend(
            q
            for q in Insight.objects.filter(
                team_id=notebook.team_id, short_id__in=added_short_ids, deleted=False
            ).values_list("query", flat=True)
            if isinstance(q, dict)
        )
    return tables_blocked_for_user(user, notebook.team, changed_queries)
