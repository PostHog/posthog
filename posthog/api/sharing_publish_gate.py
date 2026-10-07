"""Publish-time access gate for public sharing.

Shared links execute without warehouse access control (the publish act is the access
decision - see SharedLinkUser), so the gate moves to the moment of publishing: the member
enabling a share must be able to run every query it exposes. Otherwise sharing would be an
escalation channel - save a query over a restricted table, publish, read it through the
public link.
"""

from typing import Any

from django.db.models import Q

from rest_framework import serializers

from posthog.api.query_access_check import blocked_access_for_user
from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.sharing_configuration import SharingConfiguration

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.exports.backend.facade.api import subscription_delivers_insight, subscription_delivers_whole_dashboard
from products.notebooks.backend.facade.content import extract_inline_query_nodes, extract_referenced_insight_short_ids
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight


def check_can_add_insight_to_shared_dashboard(
    user: User,
    dashboard: Dashboard,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> None:
    """Raise if binding an insight with this query to the dashboard would expose, through the
    dashboard's public link or a subscription that delivers the whole dashboard, a query the
    editor can't run themselves. No-op when the dashboard has neither, the org lacks the access
    control entitlement, or the editor is an org admin."""
    if not isinstance(query, dict):
        return
    if not dashboard.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return
    uac = user_access_control or UserAccessControl(user=user, team=dashboard.team)
    # org admins have full access, so skip the gate for a faster write
    if uac.is_organization_admin:
        return
    exposure = exposure_without_viewer_check(dashboard)
    if exposure is None:
        return
    blocked = blocked_access_for_user(user, dashboard.team, [query])
    if blocked:
        blocked_list = ", ".join(f"`{name}`" for name in blocked)
        raise serializers.ValidationError(
            f"Can't add this insight: you don't have access to {blocked_list}, and {exposure}."
        )


def blocked_access_for_publisher(user: User, team: Team, config: SharingConfiguration) -> list[str]:
    """
    Tables and runner-level resources that stop the publisher from running the shared
    artifact's queries. Each query is compiled (resolved, not executed) as the publisher,
    the same resolution the read path uses. Non-access compile errors don't gate.
    Empty list = safe to publish.
    """
    return blocked_access_for_user(user, team, _queries_exposed_by(config))


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
        team_shares = SharingConfiguration.objects.filter(
            SharingConfiguration.tokens_active_q(), team_id=artifact.team_id
        )
        # Each exposure route is a separate indexed EXISTS scoped to the team. Written as one
        # unscoped OR over the tile join, Postgres left-joins every active share across all teams
        # to every tile before it can apply the predicate.
        if team_shares.filter(insight=artifact).exists():
            return True
        # Both tile conditions stay in one filter() call so they match the same joined row.
        if team_shares.filter(
            Q(dashboard__tiles__deleted__isnull=True) | Q(dashboard__tiles__deleted=False),
            dashboard__tiles__insight=artifact,
        ).exists():
            return True
        # Notebooks reference insights inside their content JSON, so the few active notebook
        # shares per team are scanned rather than joined.
        return any(
            artifact.short_id in extract_referenced_insight_short_ids(content)
            for content in team_shares.filter(notebook__isnull=False).values_list("notebook__content", flat=True)
        )
    field = "dashboard" if isinstance(artifact, Dashboard) else "notebook"
    return SharingConfiguration.objects.filter(
        SharingConfiguration.tokens_active_q(), team_id=artifact.team_id, **{field: artifact}
    ).exists()


def exposure_without_viewer_check(artifact: "Dashboard | Insight") -> str | None:
    """Why the artifact's queries reach people whose own table access is not checked, as a clause
    that completes a validation message. None when no such route exists.

    A public link and a subscription both show results without a table-access check on the
    viewer. An edit that changes what they expose must therefore pass that check on the editor.
    """
    noun = "insight" if isinstance(artifact, Insight) else "dashboard"
    if is_publicly_shared(artifact):
        return f"this {noun} is publicly shared"
    if isinstance(artifact, Insight):
        delivered = subscription_delivers_insight(team_id=artifact.team_id, insight_id=artifact.id)
    else:
        delivered = subscription_delivers_whole_dashboard(team_id=artifact.team_id, dashboard_id=artifact.id)
    return f"a subscription delivers this {noun}" if delivered else None


def blocked_access_in_notebook_edit(user: User, notebook: Any, new_content: dict[str, Any] | None) -> list[str]:
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
    return blocked_access_for_user(user, notebook.team, changed_queries)
