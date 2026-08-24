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

from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Prefetch, QuerySet
from django.utils.timezone import now

from pydantic.dataclasses import dataclass
from rest_framework import serializers

from posthog.api.sharing_publish_gate import check_can_add_insight_to_shared_dashboard
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.user_permissions import UserPermissions

from products.dashboards.backend.facade.enums import PrivilegeLevel
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile

if TYPE_CHECKING:
    from products.product_analytics.backend.facade.models import Insight


class DashboardNotFound(Exception):
    """A requested dashboard is not one this team can place an insight on."""


class DashboardNotEditable(Exception):
    """The requester may not change which insights sit on this dashboard."""

    def __init__(self, dashboard_id: int) -> None:
        super().__init__(str(dashboard_id))
        self.dashboard_id = dashboard_id


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


def dashboard_refs(dashboard_ids: Sequence[int]) -> tuple[DashboardRef, ...]:
    """Dashboard IDs and names for callers that already validated the dashboard IDs."""
    return _refs_in_given_order(dashboard_ids)


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


def tile_ids_prefetch() -> Prefetch:
    """Prefetch of an insight's tiles carrying only the columns a basic insight payload renders."""
    return Prefetch(
        "dashboard_tiles",
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


def restore_tiles_for_insights(insight_ids: Collection[int], *, user_permissions: UserPermissions) -> None:
    """Re-activate soft-deleted tiles of these insights, on live dashboards the requester may edit.

    Run inside the caller's transaction: it is one half of restoring the insights themselves.
    Mirrors the per-dashboard CAN_EDIT check membership updates apply, so a restore can't force an
    insight back onto a dashboard the requester can only view. Tiles removed before the delete may
    also reappear; acceptable for the immediate-undo case this backs.
    """
    candidate_tiles = DashboardTile.objects_including_soft_deleted.filter(
        insight_id__in=insight_ids, deleted=True, dashboard__deleted=False
    ).select_related("dashboard")
    restorable_tile_ids = [
        tile.id
        for tile in candidate_tiles
        if user_permissions.dashboard(tile.dashboard).effective_privilege_level == PrivilegeLevel.CAN_EDIT
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
    user_permissions: UserPermissions,
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
    for dashboard in dashboards:
        # Adding a tile is an edit of the dashboard, so a restricted dashboard the requester
        # can't edit must not be writable here either.
        if user_permissions.dashboard(dashboard).effective_privilege_level != PrivilegeLevel.CAN_EDIT:
            raise CannotAddToDashboard(dashboard.id)
        if dashboard.team_id != team_id:
            raise DashboardNotFound
        # The dashboard's public link must not expose a query the editor can't run.
        check_can_add_insight_to_shared_dashboard(user, dashboard, query, user_access_control)
    return InsightTilePlacement(dashboards)


def update_insight_dashboard_membership(
    *,
    insight: "Insight",
    dashboard_ids: Sequence[int],
    user: User,
    user_permissions: UserPermissions,
    user_access_control: UserAccessControl | None,
) -> MembershipChange | None:
    """Move an insight on and off dashboards until it sits on exactly `dashboard_ids`.

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
    for dashboard in Dashboard.objects.filter(id__in=ids_to_add):
        # Does the requester have permission to add to this dashboard? If it is restricted, the
        # patch would otherwise make the insight restricted too.
        if user_permissions.dashboard(dashboard).effective_privilege_level != PrivilegeLevel.CAN_EDIT:
            raise CannotAddToDashboard(dashboard.id)

        if dashboard.team != insight.team:
            raise DashboardNotFound

        # The dashboard's public link must not expose a query the editor can't run.
        check_can_add_insight_to_shared_dashboard(user, dashboard, insight.query, user_access_control)

        tile, _ = DashboardTile.objects_including_soft_deleted.get_or_create(insight=insight, dashboard=dashboard)
        if tile.deleted:
            tile.deleted = False
            tile.save()

        added_dashboard_ids.append(dashboard.id)

    removed_dashboard_ids: list[int] = []
    if ids_to_remove:
        # nosemgrep: idor-lookup-without-team (team check after lookup)
        for dashboard in Dashboard.objects.filter(id__in=ids_to_remove):
            if user_permissions.dashboard(dashboard).effective_privilege_level != PrivilegeLevel.CAN_EDIT:
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
    "DashboardRef",
    "DashboardTileBasicSerializer",
    "InsightTilePlacement",
    "MembershipChange",
    "active_tile_count",
    "dashboard_refs",
    "hide_tiles_for_insights",
    "insight_has_listed_tile",
    "insight_ids_on_dashboard",
    "plan_insight_tile_placement",
    "restore_tiles_for_insights",
    "tile_for_insight_on_dashboard",
    "tile_for_render",
    "tile_ids_prefetch",
    "tile_permissions_prefetch",
    "unknown_dashboard_ids",
    "update_insight_dashboard_membership",
]
