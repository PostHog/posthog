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

from posthog.hogql.escape_sql import backquote_escape_chars_map

from posthog.api.property_filter_access_gate import table_blocking_property_filters
from posthog.api.query_access_check import denied_query_resources
from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.sharing_configuration import SharingConfiguration

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.facade.content import extract_inline_query_nodes, extract_referenced_insight_short_ids
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.facade.api import (
    dashboard_has_active_full_subscription,
    insight_has_active_subscription,
)


def dashboard_shared_or_subscribed(dashboard: Dashboard) -> str | None:
    """How the dashboard's tiles reach readers who never pass a table-access check: through its
    public link, or through a subscription that delivers the whole dashboard. None when neither
    applies, so a tile write needs no access check."""
    if is_publicly_shared(dashboard):
        return "publicly shared"
    if dashboard_has_active_full_subscription(dashboard.id):
        return "delivered by a subscription"
    return None


def insight_shared_or_subscribed(insight: Insight) -> str | None:
    """How the insight reaches readers who never pass a table-access check: through a public
    link (its own, or a shared dashboard or notebook that shows it), or through a subscription
    that delivers it. None when neither applies, so a query edit needs no access check."""
    if is_publicly_shared(insight):
        return "publicly shared"
    if insight_has_active_subscription(insight.id):
        return "delivered by a subscription"
    return None


def insight_query_access_error(
    user: User,
    insight: Insight,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> str | None:
    """The validation message that stops saving this query on the insight, when the insight is
    shared or subscribed and the editor can't run the query themselves. None when the save may
    go ahead: nothing exposes the insight, the org lacks the access control entitlement, or the
    editor is an org admin."""
    if not isinstance(query, dict):
        return None
    if not insight.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return None
    uac = user_access_control or UserAccessControl(user=user, team=insight.team)
    # org admins have full access, so skip the gate for a faster save
    if uac.is_organization_admin:
        return None
    exposure = insight_shared_or_subscribed(insight)
    if exposure is None:
        return None
    denied_resources = denied_query_resources(user, insight.team, [query])
    if not denied_resources:
        return None
    denied_names = ", ".join(f"`{name}`" for name in denied_resources)
    return f"Can't save this query: you don't have access to {denied_names}, and this insight is {exposure}."


def check_can_add_insight_to_dashboard(
    user: User,
    dashboard: Dashboard,
    query: Any,
    user_access_control: UserAccessControl | None = None,
) -> None:
    """Raise if binding an insight with this query to the dashboard would expose, through the
    dashboard's public link or a subscription that delivers it in full, a query the editor can't
    run themselves. No-op when the dashboard reaches no such reader, the org lacks the access
    control entitlement, or the editor is an org admin."""
    if not isinstance(query, dict):
        return
    if not dashboard.team.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
        return
    uac = user_access_control or UserAccessControl(user=user, team=dashboard.team)
    # org admins have full access, so skip the gate for a faster write
    if uac.is_organization_admin:
        return
    exposure = dashboard_shared_or_subscribed(dashboard)
    if exposure is None:
        return
    denied_resources = denied_query_resources(user, dashboard.team, [query])
    if denied_resources:
        denied_names = ", ".join(f"`{name}`" for name in denied_resources)
        raise serializers.ValidationError(
            f"Can't add this insight: you don't have access to {denied_names}, and this dashboard is {exposure}."
        )


def denied_resources_in_share(user: User, team: Team, config: SharingConfiguration) -> list[str]:
    """
    Tables and runner-level resources that stop the publisher from running the shared
    artifact's queries. Each query is compiled (resolved, not executed) as the publisher,
    the same resolution the read path uses. Non-access compile errors don't gate.
    Empty list = safe to publish.
    """
    denied_resources = denied_query_resources(user, team, _queries_exposed_by(config))
    # A dashboard's own filters and tile overrides run inside every tile, and they could have
    # been saved before the dashboard was shared, when the save-time check did not apply.
    if config.dashboard is not None:
        leaves = dashboard_filter_leaves(config.dashboard.filters)
        for overrides in config.dashboard.tiles.values_list("filters_overrides", flat=True):
            leaves += dashboard_filter_leaves(overrides)
        if (table := table_blocking_property_filters(user, team, leaves)) and table not in denied_resources:
            denied_resources = sorted([*denied_resources, table])
    return denied_resources


def dashboard_filter_leaves(filters: Any) -> list[dict[str, Any]]:
    """The property filters of a dashboard filter set, plus its breakdowns as HogQL filters, in
    the shape `table_blocking_property_filters` checks. A leaf without a string type is skipped,
    since the check cannot classify it."""
    if not isinstance(filters, dict):
        return []
    properties = filters.get("properties")
    leaves = [
        leaf
        for leaf in (properties if isinstance(properties, list) else [])
        if isinstance(leaf, dict) and isinstance(leaf.get("type"), str)
    ]
    breakdown_filter = filters.get("breakdown_filter")
    if not isinstance(breakdown_filter, dict):
        return leaves
    breakdowns = breakdown_filter.get("breakdowns")
    pairs = [
        (breakdown.get("type"), breakdown.get("property"))
        for breakdown in (breakdowns if isinstance(breakdowns, list) else [])
        if isinstance(breakdown, dict)
    ]
    pairs.append((breakdown_filter.get("breakdown_type"), breakdown_filter.get("breakdown")))
    for breakdown_type, value in pairs:
        # A funnel breakdown is a list of values, each read like a single breakdown.
        for key in value if isinstance(value, list) else [value]:
            if isinstance(breakdown_type, str) and isinstance(key, str):
                if expr := _breakdown_as_hogql(breakdown_type, key):
                    leaves.append({"type": "hogql", "key": expr})
    return leaves


def _breakdown_as_hogql(breakdown_type: str, key: str) -> str | None:
    """The expression a breakdown reads, as the trends breakdown builds it, for the breakdown
    types that can reach a warehouse table. None for the types that cannot."""
    if breakdown_type in ("hogql", "event_metadata"):
        return key
    if breakdown_type == "data_warehouse":
        chain = key.split(".")
    elif breakdown_type == "data_warehouse_person_property":
        chain = ["person", *key.split(".")]
    else:
        return None
    # Every part is quoted, so a part that reads as a keyword, such as `null`, stays a field name,
    # and a part the printer would refuse does not raise here.
    return ".".join("`" + "".join(backquote_escape_chars_map.get(c, c) for c in part) + "`" for part in chain)


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


def denied_resources_in_notebook_edit(user: User, notebook: Any, new_content: dict[str, Any] | None) -> list[str]:
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
    return denied_query_resources(user, notebook.team, changed_queries)
