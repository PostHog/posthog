"""Server-side query rescoping for guest users on the /query/ endpoint.

Guests authenticate as regular session users and reach /query/ via the normal
request path; the `GuestDeflectionMiddleware` gates access (header must name a
granted resource), but the middleware does not inspect the query body.

Without this module, a guest with any valid scene-resource header could POST a
body like `{"query": {"kind": "EventsQuery", "select": ["*"]}}` and read all
team events. This module rescopes the query body before it reaches the query
runner:

1. Resolve the scene-resource header to a granted insight (for dashboard
   grants, the header identifies the tile's insight).
2. Load the insight's saved query from the DB (`Insight.query`).
3. Start from the saved query, overlay only whitelisted fields from the client
   body. The whitelist is generated from `@guestOverridable` JSDoc annotations
   in `frontend/src/queries/schema/schema-general.ts` (see
   `bin/generate-guest-overridable.py`).

The result is that the executed query's structural shape (kind, series,
source, HogQL text) comes from the saved insight. The client can only change
fields that correspond to UI-level viewer controls (date range, properties,
breakdown, filter test accounts, etc.).
"""

from __future__ import annotations

from typing import Any

from rest_framework.exceptions import NotFound
from rest_framework.request import Request

from posthog.models.insight import Insight
from posthog.rbac._generated_guest_overridable import GUEST_OVERRIDABLE_FIELDS

from ee.models.rbac.access_control import AccessControl

SCENE_RESOURCE_HEADER = "X-PostHog-Scene-Resource"


def user_is_guest_for_request(request: Request) -> bool:
    """Thin wrapper over the request-scoped cache so `QueryViewSet.create` can ask
    "is this user a guest?" without re-querying — the middleware has already populated
    the cache for this request."""
    from posthog.rbac.guest_request_cache import is_user_guest_in_any_org

    return is_user_guest_in_any_org(request)


def rescope_guest_query(request: Request, team_id: int) -> None:
    """Mutate `request.data['query']` in place so only whitelisted fields from the
    client body are honored; everything else comes from the guest's granted
    resource. Raises NotFound if no grant matches the scene-resource header, if
    the saved query is missing, or if the client-submitted kind doesn't match
    the saved kind.

    `team_id` is the team owning the request — it scopes the grant lookup and the
    saved-insight lookup so a guest with a grant in team A can't satisfy a query
    targeting team B.
    """
    scene = request.headers.get(SCENE_RESOURCE_HEADER) or ""
    resource_type, _, resource_id = scene.partition(":")
    resource_type = resource_type.strip()
    resource_id = resource_id.strip()
    if resource_type not in ("dashboard", "insight") or not resource_id:
        raise NotFound()

    saved_insight = _load_insight_for_grant(request.user, resource_type, resource_id, request, team_id)
    if saved_insight is None or not isinstance(saved_insight.query, dict):
        raise NotFound()

    saved_query = _unwrap_insight_query(saved_insight.query)
    saved_kind = saved_query.get("kind")
    if not saved_kind:
        raise NotFound()

    client_query = ((request.data or {}).get("query") or {}) if isinstance(request.data, dict) else {}
    if not isinstance(client_query, dict):
        client_query = {}

    # Kind must match exactly. The scene-resource header binds the query to a
    # specific saved insight; a TrendsQuery grant cannot be used to run an
    # EventsQuery/ActorsQuery/HogQLQuery.
    if client_query.get("kind") and client_query["kind"] != saved_kind:
        raise NotFound()

    overridable = GUEST_OVERRIDABLE_FIELDS.get(saved_kind, frozenset())

    # Start from the saved query, overlay whitelisted fields from the client.
    # Any field not in the whitelist is discarded (including `series`, `source`,
    # `query` HogQL text, `events`, `actions`, etc.) — the structural shape of
    # the saved insight is preserved.
    rescoped = dict(saved_query)
    for field in overridable:
        if field in client_query:
            rescoped[field] = client_query[field]

    if not isinstance(request.data, dict):
        # Shouldn't happen for JSON-parsed requests, but defend anyway.
        raise NotFound()
    request.data["query"] = rescoped


def _load_insight_for_grant(
    user, resource_type: str, resource_id: str, request: Request, team_id: int
) -> Insight | None:
    """Return the Insight whose saved query should be used for this request.

    For `insight` grants: look up the insight by short_id within the request's team,
    verifying the grant against the same team. `Insight.short_id` is unique per team,
    not globally — without the team filter, two teams' insights sharing a short_id
    would collide.
    For `dashboard` grants: the header names a dashboard, but a query runs for a
    specific tile. The FE sends the tile insight's short_id alongside in a sibling
    header; we verify that short_id belongs to a tile of the granted dashboard
    before using it.
    """
    # The header carries URL-style identifiers (short_id for insights, numeric
    # PK for dashboards). The AC table stores numeric PKs for all resources, so
    # insight short_ids must be translated before the AC lookup.
    ac_resource_id = _header_to_ac_resource_id(resource_type, resource_id, team_id)
    if ac_resource_id is None:
        return None

    grant_exists = AccessControl.objects.filter(
        team_id=team_id,
        organization_member__user=user,
        organization_member__is_guest=True,
        resource=resource_type,
        resource_id=ac_resource_id,
    ).exists()
    if not grant_exists:
        return None

    if resource_type == "insight":
        return Insight.objects.filter(team_id=team_id, short_id=resource_id, deleted=False).first()

    # dashboard grant — tile insight is named in a sibling header alongside the
    # dashboard scene resource. Verify that short_id belongs to a tile of the
    # granted dashboard before using it.
    tile_short_id = _tile_short_id_from_request(request)
    if not tile_short_id or not resource_id.isdigit():
        return None
    dashboard_id = int(resource_id)
    return (
        Insight.objects.filter(
            team_id=team_id,
            short_id=tile_short_id,
            deleted=False,
            dashboard_tiles__dashboard_id=dashboard_id,
        )
        .distinct()
        .first()
    )


def _header_to_ac_resource_id(resource_type: str, header_resource_id: str, team_id: int) -> str | None:
    """Translate a URL-style identifier from the scene-resource header into the
    numeric-PK form that `AccessControl.resource_id` stores, scoped to `team_id`.

    Dashboards are addressed by numeric PK on both sides, so no translation.
    Insights are addressed by short_id in the header; look up the PK *within the
    request's team* (short_id is per-team, not globally unique).
    """
    if resource_type == "dashboard":
        return header_resource_id if header_resource_id.isdigit() else None
    if resource_type == "insight":
        if header_resource_id.isdigit():
            return header_resource_id
        pk = Insight.objects.filter(team_id=team_id, short_id=header_resource_id).values_list("id", flat=True).first()
        return str(pk) if pk is not None else None
    return None


def _tile_short_id_from_request(request: Request) -> str | None:
    """The FE stamps the tile insight's short_id in a sibling header alongside
    the dashboard scene resource. Keeps the dashboard-grant case unambiguous
    without requiring the client to restate which tile it is querying."""
    tile_header = request.headers.get("X-PostHog-Scene-Tile-Insight-Short-Id")
    if tile_header and tile_header.strip():
        return tile_header.strip()
    return None


def _unwrap_insight_query(query: dict[str, Any]) -> dict[str, Any]:
    """Saved insights store `InsightVizNode { source: TrendsQuery{...} }` wrappers.
    The /query/ endpoint expects the inner query node. Unwrap if present."""
    source = query.get("source") if query.get("kind") == "InsightVizNode" else None
    return source if isinstance(source, dict) else query
