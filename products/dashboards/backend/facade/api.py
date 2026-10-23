"""
Dashboard membership of an insight, for callers outside this product.

An insight sits on a dashboard through a tile, and a tile is a dashboards row: the queries that
find it, the permission checks that guard it, its JSON shape and its soft-delete semantics all
belong here. The insight API passes ids and gets back ids, counts and rendered tile JSON, so it
never has to hold the tile or dashboard model classes itself.

Everything that writes runs inside the caller's transaction; each function says so where it
matters. Refusals are raised as the error types defined here — the caller decides which HTTP
response they become.
"""

import re
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Prefetch, QuerySet
from django.utils.timezone import now

from pydantic.dataclasses import dataclass
from rest_framework import serializers

from posthog.api.sharing_publish_gate import check_can_add_insight_to_dashboard
from posthog.helpers.dashboard_templates import create_from_template
from posthog.models.user import User
from posthog.models.user_home_settings import UserHomeSettings

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import DashboardTile

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.product_analytics.backend.facade.models import Insight


class DashboardNotFound(Exception):
    """A requested dashboard is not one this team can place an insight on."""


class DashboardNotEditable(Exception):
    """The requester may not change which insights sit on this dashboard."""

    def __init__(self, dashboard_id: int) -> None:
        super().__init__(str(dashboard_id))
        self.dashboard_id = dashboard_id


class DashboardNotViewable(Exception):
    """The requester may not view this dashboard."""


class CannotAddToDashboard(DashboardNotEditable):
    """Raised while placing an insight on a dashboard the requester can only view."""


class CannotRemoveFromDashboard(DashboardNotEditable):
    """Raised while taking an insight off a dashboard the requester can only view."""


@dataclass(frozen=True)
class DashboardRef:
    """A dashboard as insight payloads and activity logs refer to it."""

    id: int
    name: str | None


@dataclass(frozen=True)
class MembershipChange:
    """What one membership write changed, for the caller's analytics events and activity log."""

    added_dashboard_ids: tuple[int, ...]
    removed_dashboard_ids: tuple[int, ...]
    dashboards: tuple[DashboardRef, ...]


# The tile shape an insight payload carries for each dashboard it sits on. No docstring: it would
# land in the generated OpenAPI component as a description.
class DashboardTileBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardTile
        fields = ["id", "dashboard_id", "deleted"]


def _refs_in_given_order(dashboard_ids: Sequence[int]) -> tuple[DashboardRef, ...]:
    # Callers pass ids they have already validated against the team; this reads names only.
    # nosemgrep: idor-lookup-without-team
    names = dict(Dashboard.objects.filter(id__in=dashboard_ids).values_list("id", "name"))
    return tuple(
        DashboardRef(id=dashboard_id, name=names[dashboard_id])
        for dashboard_id in dashboard_ids
        if dashboard_id in names
    )


@dataclass(frozen=True)
class DashboardInsightTile:
    insight_short_id: str
    filters_overrides: dict[str, Any] | None


@dataclass(frozen=True)
class DashboardInsights:
    dashboard_id: int
    name: str | None
    filters: dict[str, Any]
    variables: dict[str, Any] | None
    tiles: tuple[DashboardInsightTile, ...]


def home_dashboard_insights(*, team: "Team", user: User, limit: int) -> DashboardInsights | None:
    homepage = UserHomeSettings.objects.filter(team=team, user=user).values_list("homepage", flat=True).first()
    match = re.search(r"/dashboard/(\d+)", str((homepage or {}).get("pathname") or ""))
    dashboard_id = int(match.group(1)) if match else team.primary_dashboard_id
    if dashboard_id is None:
        return None
    return dashboard_insights(team=team, user=user, dashboard_id=dashboard_id, limit=limit)


def dashboard_insights(*, team: "Team", user: User, dashboard_id: int, limit: int) -> DashboardInsights | None:
    return _dashboard_insights(team, user, dashboard_id, limit)


def dashboard_insight_tile(*, team: "Team", user: User, dashboard_id: int, short_id: str) -> DashboardInsights | None:
    found = _dashboard_insights(team, user, dashboard_id, 1, short_id=short_id)
    return found if found is not None and found.tiles else None


def _dashboard_insights(
    team: "Team", user: User, dashboard_id: int, limit: int, short_id: str | None = None
) -> DashboardInsights | None:
    dashboard = Dashboard.objects.filter(team_id=team.id, pk=dashboard_id).first()
    access = UserAccessControl(user=user, team=team)
    if dashboard is None or not access.check_access_level_for_object(dashboard, "viewer"):
        return None
    insight_tiles = DashboardTile.objects.filter(dashboard=dashboard, insight__isnull=False, insight__deleted=False)
    if short_id is not None:
        insight_tiles = insight_tiles.filter(insight__short_id=short_id)
    tiles = DashboardTile.sort_tiles_by_layout(insight_tiles.select_related("insight"))
    return DashboardInsights(
        dashboard_id=dashboard.id,
        name=dashboard.name,
        filters=dashboard.filters or {},
        variables=dashboard.variables or None,
        tiles=tuple(
            DashboardInsightTile(
                insight_short_id=tile.insight.short_id, filters_overrides=tile.filters_overrides or None
            )
            for tile in tiles[:limit]
            if tile.insight is not None
        ),
    )


def viewable_dashboard_ref(dashboard_id: int, *, team: "Team", user: User) -> DashboardRef | None:
    """The dashboard as a ref when it is live in this team and the user may view it, else None.

    Object-level access rules can hide one dashboard from a user who has team-wide dashboard access.
    """
    dashboard = Dashboard.objects.filter(team_id=team.id, pk=dashboard_id).first()
    if dashboard is None:
        return None
    if UserAccessControl(user=user, team=team).check_access_level_for_object(dashboard, "viewer") is False:
        return None
    return DashboardRef(id=dashboard.id, name=dashboard.name)


def create_dashboard_from_tiles(
    *,
    team: "Team",
    user: User,
    name: str,
    description: str,
    filters: dict[str, Any],
    tiles: list[dict[str, Any]],
    tags: list[str],
) -> DashboardRef:
    """Create a dashboard from template-shaped tile definitions, for products that build dashboards in code.

    Runs inside the caller's transaction, so a failure part way leaves no dashboard behind when the caller rolls back.
    """
    template = DashboardTemplate(
        template_name=name, dashboard_description=description, dashboard_filters=filters, tiles=tiles, tags=tags
    )
    dashboard = Dashboard.objects.create(
        team_id=team.id, name=name, created_by=user, creation_mode=Dashboard.CreationMode.TEMPLATE
    )
    create_from_template(dashboard, template, user, user_access_control=UserAccessControl(user=user, team=team))
    return DashboardRef(id=dashboard.id, name=dashboard.name)


def dashboard_refs(dashboard_ids: Sequence[int]) -> tuple[DashboardRef, ...]:
    """Dashboard IDs and names for callers that already validated the dashboard IDs."""
    return _refs_in_given_order(dashboard_ids)


def dashboards_by_insight(insight_ids: Collection[int], *, team_id: int) -> dict[int, tuple[DashboardRef, ...]]:
    """The listed dashboards each insight of this team sits on, oldest tile first, in one query.

    Deleted tiles, dashboards and insights do not count. An insight on no such dashboard has no key.
    """
    rows = (
        DashboardTile.objects.filter(dashboard__team_id=team_id, insight_id__in=insight_ids, insight__deleted=False)
        .exclude(dashboard__creation_mode=Dashboard.CreationMode.UNLISTED)
        .order_by("insight_id", "id")
        .values_list("insight_id", "dashboard_id", "dashboard__name")
    )
    refs: dict[int, list[DashboardRef]] = {}
    for insight_id, dashboard_id, name in rows:
        refs.setdefault(insight_id, []).append(DashboardRef(id=dashboard_id, name=name))
    return {insight_id: tuple(dashboards) for insight_id, dashboards in refs.items()}


def dashboard_exists(dashboard_id: int) -> bool:
    """Whether a live dashboard has this id, in any team.

    A request field that names a dashboard checks this first, and the team check follows.
    """
    # The caller compares the dashboard's team with its own right after this lookup.
    # nosemgrep: idor-lookup-without-team
    return Dashboard.objects.filter(pk=dashboard_id).exists()


def viewable_dashboard_id(*, team_id: int, dashboard_id: int, user_access_control: UserAccessControl) -> int:
    """The id of a live dashboard of this team that the user may view.

    Raises `DashboardNotFound` when the team has no live dashboard with this id, and
    `DashboardNotViewable` when object-level access rules hide it from the user.
    """
    dashboard = Dashboard.objects.filter(team_id=team_id, pk=dashboard_id).first()
    if dashboard is None:
        raise DashboardNotFound(str(dashboard_id))
    if not user_access_control.check_access_level_for_object(dashboard, "viewer"):
        raise DashboardNotViewable(str(dashboard_id))
    return dashboard.id


def live_tile_insight_ids(dashboard_id: int) -> list[int]:
    """Ids of the insights on this dashboard's live tiles, leaving out deleted insights."""
    # The caller resolved this id through a team-scoped dashboard lookup first.
    # nosemgrep: idor-lookup-without-team
    return list(
        DashboardTile.objects.filter(
            dashboard_id=dashboard_id, insight_id__isnull=False, insight__deleted=False
        ).values_list("insight_id", flat=True)
    )


def unknown_dashboard_ids(dashboard_ids: Collection[int], *, team_id: int) -> list[int]:
    """Which of these ids are not a live dashboard of this team, in the order they were given.

    Live means not soft-deleted, so an id that used to work stops validating once its dashboard
    is deleted.
    """
    known = set(Dashboard.objects.filter(team_id=team_id, id__in=dashboard_ids).values_list("id", flat=True))
    return [dashboard_id for dashboard_id in dict.fromkeys(dashboard_ids) if dashboard_id not in known]


def active_tile_count(dashboard_id: int) -> int:
    """How many live tiles a dashboard carries, for the per-dashboard insight limit."""
    # The caller resolved this id through the team-scoped dashboards field first.
    # nosemgrep: idor-lookup-without-team
    return DashboardTile.objects.filter(dashboard_id=dashboard_id).exclude(deleted=True).count()


def tile_ids_prefetch(lookup: str = "dashboard_tiles") -> Prefetch:
    """Prefetch of an insight's tiles carrying only the columns a basic insight payload renders.
    `lookup` is the path from the queryset's model to the insight's tiles."""
    return Prefetch(
        lookup,
        queryset=DashboardTile.objects.only("id", "dashboard_id", "deleted", "insight_id"),
    )


def tile_permissions_prefetch() -> Prefetch:
    """Prefetch of an insight's tiles with the joins the dashboard permission checks read."""
    return Prefetch(
        "dashboard_tiles",
        queryset=DashboardTile.objects.select_related("dashboard__team__organization"),
    )


def insight_has_listed_tile() -> Exists:
    """Subquery over insights: this insight has a tile on a dashboard the UI lists."""
    return Exists(DashboardTile.objects.filter(insight=OuterRef("pk")).exclude(dashboard__creation_mode="unlisted"))


def insight_ids_on_dashboard(dashboard_id: int) -> QuerySet:
    """Ids of the insights with a tile on this dashboard, as a subquery for `id__in`."""
    # Filtering a list the caller has already scoped to its own team.
    # nosemgrep: idor-lookup-without-team
    return DashboardTile.objects.filter(dashboard__id=dashboard_id).values_list("insight__id", flat=True).all()


def tile_for_insight_on_dashboard(*, insight_id: int, dashboard_id: int | str) -> DashboardTile | None:
    """The tile that places one insight on one dashboard, with its dashboard loaded.

    Returns a tile whatever the requester may see: the caller checks dashboard access on the
    result, because the checks differ between session and sharing-token callers.
    """
    # nosemgrep: idor-lookup-without-team
    return (
        DashboardTile.objects.filter(dashboard__id=dashboard_id, insight__id=insight_id)
        .select_related("dashboard")
        .first()
    )


def tile_for_render(*, insight: "Insight", dashboard: Dashboard) -> DashboardTile | None:
    """The tile an insight renders as on a dashboard, with the relations the render reads."""
    return DashboardTile.dashboard_queryset(DashboardTile.objects.filter(insight=insight, dashboard=dashboard)).first()


def hide_tiles_for_insights(insight_ids: Collection[int]) -> None:
    """Soft-delete every tile of these insights, tiles already soft-deleted included.

    Run inside the caller's transaction: it is one half of soft-deleting the insights themselves.
    """
    DashboardTile.objects_including_soft_deleted.filter(insight_id__in=insight_ids).update(deleted=True)


def _dashboard_edit_access_by_team(
    dashboards: Collection[Dashboard], user_access_control: UserAccessControl | None
) -> dict[int, UserAccessControl]:
    """Resolve dashboard edit access against each dashboard's own team.

    A tile's dashboard can belong to a sibling environment's team in the same project, and the
    request-scoped UserAccessControl is bound to the requesting team. Resolving a sibling's
    dashboard through it reads the wrong team's rules and can skip a dashboard the requester may
    edit. `for_team_ids` returns one instance per dashboard team with the same user and
    organization, so project scope is preserved.
    """
    if user_access_control is None:
        return {}
    return user_access_control.for_team_ids({dashboard.team_id for dashboard in dashboards})


def insights_with_dashboard_edit_access(
    insight_ids: Collection[int], *, user_access_control: UserAccessControl, project_id: int
) -> set[int]:
    tiles = list(
        DashboardTile.objects_including_soft_deleted.filter(
            insight_id__in=insight_ids, dashboard__team__project_id=project_id, dashboard__deleted=False
        ).select_related("dashboard")
    )
    access_by_team = _dashboard_edit_access_by_team([tile.dashboard for tile in tiles], user_access_control)
    editable: set[int] = set()
    linked: set[int] = set()
    limited_dashboards: dict[int, bool] = {}
    editable_dashboards: dict[int, bool] = {}
    for tile in tiles:
        if tile.insight_id is None:
            continue
        access = access_by_team[tile.dashboard.team_id]
        if tile.dashboard_id not in limited_dashboards:
            limited_dashboards[tile.dashboard_id] = access.has_object_access_limit("dashboard", str(tile.dashboard_id))
        limited = limited_dashboards[tile.dashboard_id]
        # Hidden restricted tiles retain their policy; removed unrestricted tiles cannot grant access.
        if tile.deleted and not limited:
            continue
        linked.add(tile.insight_id)
        if tile.dashboard_id not in editable_dashboards:
            editable_dashboards[tile.dashboard_id] = not limited or access.check_access_level_for_object(
                tile.dashboard, "editor"
            )
        if editable_dashboards[tile.dashboard_id]:
            editable.add(tile.insight_id)
    return editable | (set(insight_ids) - linked)


def restore_tiles_for_insights(insight_ids: Collection[int], *, user_access_control: UserAccessControl) -> None:
    """Re-activate soft-deleted tiles of these insights, on live dashboards the requester may edit.

    Run inside the caller's transaction: it is one half of restoring the insights themselves.
    Tiles removed before the delete may also reappear; acceptable for the immediate-undo case
    this backs.
    """
    candidate_tiles = list(
        DashboardTile.objects_including_soft_deleted.filter(
            insight_id__in=insight_ids, deleted=True, dashboard__deleted=False
        ).select_related("dashboard")
    )
    access_by_team = _dashboard_edit_access_by_team([tile.dashboard for tile in candidate_tiles], user_access_control)
    restorable_tile_ids = [
        tile.id
        for tile in candidate_tiles
        if access_by_team[tile.dashboard.team_id].check_access_level_for_object(tile.dashboard, "editor")
    ]
    if restorable_tile_ids:
        DashboardTile.objects_including_soft_deleted.filter(id__in=restorable_tile_ids).update(deleted=False)


class InsightTilePlacement:
    """Dashboards cleared to receive a tile for one insight.

    Built by `plan_insight_tile_placement` before the insight row exists, so a refusal can't leave
    an orphaned insight behind, then applied with `create_tiles` once it does. Holding the
    dashboards it read is what keeps applying free of a second read.
    """

    def __init__(self, dashboards: list[Dashboard]) -> None:
        self._dashboards = dashboards

    @property
    def dashboards(self) -> tuple[DashboardRef, ...]:
        return tuple(DashboardRef(id=dashboard.id, name=dashboard.name) for dashboard in self._dashboards)

    def create_tiles(self, insight: "Insight") -> tuple[DashboardRef, ...]:
        """Place the insight on every cleared dashboard, and report which ones those were."""
        for dashboard in self._dashboards:
            DashboardTile.objects.create(
                insight=insight, dashboard=dashboard, team_id=dashboard.team_id, last_refresh=now()
            )
        return self.dashboards


def plan_insight_tile_placement(
    *,
    dashboard_ids: Sequence[int],
    team_id: int,
    query: Any,
    user: User,
    user_access_control: UserAccessControl | None,
) -> InsightTilePlacement:
    """Check that an insight carrying `query` may be placed on these dashboards.

    Raises `CannotAddToDashboard` when the requester can only view one of them, `DashboardNotFound`
    when one belongs to another team, and the shared-dashboard publish gate's own ValidationError
    when the query would reach further through a dashboard's public link than the requester can.
    """
    # nosemgrep: idor-lookup-without-team (team check below)
    found = {dashboard.id: dashboard for dashboard in Dashboard.objects.filter(id__in=dashboard_ids)}
    dashboards = [found[dashboard_id] for dashboard_id in dict.fromkeys(dashboard_ids) if dashboard_id in found]
    access_by_team = _dashboard_edit_access_by_team(dashboards, user_access_control)
    for dashboard in dashboards:
        if dashboard.team_id != team_id:
            raise DashboardNotFound
        # Adding a tile is an edit of the dashboard.
        if user_access_control is not None and not access_by_team[dashboard.team_id].check_access_level_for_object(
            dashboard, "editor"
        ):
            raise CannotAddToDashboard(dashboard.id)
        # The dashboard's public link or subscription must not expose a query the editor can't run.
        check_can_add_insight_to_dashboard(user, dashboard, query, user_access_control)
    return InsightTilePlacement(dashboards)


def update_insight_dashboard_membership(
    *,
    insight: "Insight",
    dashboard_ids: Sequence[int],
    query: Any,
    user: User,
    user_access_control: UserAccessControl | None,
) -> MembershipChange | None:
    """Move an insight on and off dashboards until it sits on exactly `dashboard_ids`.

    `query` is the query the insight will run once the caller's write lands, not the stored one:
    a PATCH that changes the query and the dashboards together must gate on the incoming query.

    Returns None when it already does. Adding restores the insight's previously removed tile
    rather than creating a second one; removing soft-deletes the tile so the same restore works
    next time. Refusals raise `CannotAddToDashboard`, `CannotRemoveFromDashboard` or
    `DashboardNotFound` before anything else is written for that dashboard.

    Run inside the caller's transaction — a refusal partway through must not leave the insight on
    some of the dashboards but not others.

    Reads `insight.dashboard_tiles`, and leaves that prefetch stale: the writes below go through
    separate querysets, so a caller that serializes the insight afterwards has to drop the
    prefetched relation first.
    """
    old_dashboard_ids = [tile.dashboard_id for tile in insight.dashboard_tiles.all()]
    new_dashboard_ids = list(dashboard_ids)
    if sorted(old_dashboard_ids) == sorted(new_dashboard_ids):
        return None

    ids_to_add = [dashboard_id for dashboard_id in new_dashboard_ids if dashboard_id not in old_dashboard_ids]
    ids_to_remove = [dashboard_id for dashboard_id in old_dashboard_ids if dashboard_id not in new_dashboard_ids]

    added_dashboard_ids: list[int] = []
    # nosemgrep: idor-lookup-without-team (team check after lookup)
    add_dashboards = list(Dashboard.objects.filter(id__in=ids_to_add))
    add_access_by_team = _dashboard_edit_access_by_team(add_dashboards, user_access_control)
    for dashboard in add_dashboards:
        if dashboard.team != insight.team:
            raise DashboardNotFound

        if user_access_control is not None and not add_access_by_team[dashboard.team_id].check_access_level_for_object(
            dashboard, "editor"
        ):
            raise CannotAddToDashboard(dashboard.id)

        # The dashboard's public link or subscription must not expose a query the editor can't run.
        check_can_add_insight_to_dashboard(user, dashboard, query, user_access_control)

        tile, _ = DashboardTile.objects_including_soft_deleted.get_or_create(insight=insight, dashboard=dashboard)
        if tile.deleted:
            tile.deleted = False
            tile.save()

        added_dashboard_ids.append(dashboard.id)

    removed_dashboard_ids: list[int] = []
    if ids_to_remove:
        # nosemgrep: idor-lookup-without-team (team check after lookup)
        remove_dashboards = list(Dashboard.objects.filter(id__in=ids_to_remove))
        remove_access_by_team = _dashboard_edit_access_by_team(remove_dashboards, user_access_control)
        for dashboard in remove_dashboards:
            if user_access_control is not None and not remove_access_by_team[
                dashboard.team_id
            ].check_access_level_for_object(dashboard, "editor"):
                raise CannotRemoveFromDashboard(dashboard.id)

        # Capture the still-active tiles before soft-deleting so the caller can report one
        # removal per tile that is actually removed.
        tiles_to_remove = list(DashboardTile.objects.filter(dashboard_id__in=ids_to_remove, insight=insight))
        DashboardTile.objects.filter(dashboard_id__in=ids_to_remove, insight=insight).update(deleted=True)
        removed_dashboard_ids = [tile.dashboard_id for tile in tiles_to_remove]

    return MembershipChange(
        added_dashboard_ids=tuple(added_dashboard_ids),
        removed_dashboard_ids=tuple(removed_dashboard_ids),
        dashboards=_refs_in_given_order(new_dashboard_ids),
    )


__all__ = [
    "CannotAddToDashboard",
    "CannotRemoveFromDashboard",
    "DashboardNotEditable",
    "DashboardNotFound",
    "DashboardNotViewable",
    "DashboardRef",
    "DashboardTileBasicSerializer",
    "InsightTilePlacement",
    "MembershipChange",
    "active_tile_count",
    "dashboard_exists",
    "dashboard_refs",
    "hide_tiles_for_insights",
    "insight_has_listed_tile",
    "insight_ids_on_dashboard",
    "live_tile_insight_ids",
    "plan_insight_tile_placement",
    "restore_tiles_for_insights",
    "tile_for_insight_on_dashboard",
    "tile_for_render",
    "tile_ids_prefetch",
    "tile_permissions_prefetch",
    "unknown_dashboard_ids",
    "update_insight_dashboard_membership",
    "viewable_dashboard_id",
]
