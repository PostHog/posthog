"""
Dashboards and their insight tiles, for callers outside this product.

Callers read a dashboard as a `DashboardSummary` contract and check object access through its
`access_ref`, so they never hold the dashboard model class.

An insight sits on a dashboard through a tile, and a tile is a dashboards row: the queries that
find it, the permission checks that guard it, its JSON shape and its soft-delete semantics all
belong here. The insight API passes ids and gets back ids, counts and rendered tile JSON, so it
never has to hold the tile or dashboard model classes itself.

Everything that writes runs inside the caller's transaction; each function says so where it
matters. Refusals are raised as the error types defined here — the caller decides which HTTP
response they become.

The sharing publish gate and the template helper are imported at call time. They load the
subscriptions facade, which loads the exports facade, and the exports facade imports this module.
"""

import re
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.db.models import Exists, OuterRef, Prefetch, QuerySet
from django.utils.timezone import now

from posthog.helpers.full_text_search import to_search_results
from posthog.models.user import User
from posthog.models.user_home_settings import UserHomeSettings
from posthog.resource_limits import LimitKey, check_count_limit

from products.access_control.backend.facade.contracts import ObjectAccessRef
from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.dashboards.backend.facade.contracts import (
    AppliedDashboard,
    CannotAddToDashboard,
    CannotRemoveFromDashboard,
    DashboardInsights,
    DashboardInsightTile,
    DashboardInsightTileSummary,
    DashboardNotEditable,
    DashboardNotFound,
    DashboardNotViewable,
    DashboardRef,
    DashboardSummary,
    DashboardTemplateDefinition,
    DashboardTileGroupSummary,
    InsightPlacement,
    MembershipChange,
    PlacedInsightTile,
    TeamDashboardRef,
    TilePlacement,
)
from products.dashboards.backend.facade.enums import DashboardCreationMode, DashboardUsageCount
from products.dashboards.backend.logic import (
    search as search_logic,
    team_settings as team_settings_logic,
    templates as templates_logic,
    tiles as tiles_logic,
    usage as usage_logic,
    visibility as visibility_logic,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate
from products.dashboards.backend.models.dashboard_tile import DashboardTile

if TYPE_CHECKING:
    from posthog.models.team import Team

    from products.product_analytics.backend.facade.models import Insight


def _refs_in_given_order(dashboard_ids: Sequence[int]) -> tuple[DashboardRef, ...]:
    # Callers pass ids they have already validated against the team; this reads names only.
    # nosemgrep: idor-lookup-without-team
    names = dict(Dashboard.objects.filter(id__in=dashboard_ids).values_list("id", "name"))
    return tuple(
        DashboardRef(id=dashboard_id, name=names[dashboard_id])
        for dashboard_id in dashboard_ids
        if dashboard_id in names
    )


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
    from posthog.helpers.dashboard_templates import create_from_template

    create_from_template(dashboard, template, user, user_access_control=UserAccessControl(user=user, team=team))
    return DashboardRef(id=dashboard.id, name=dashboard.name)


def dashboard_refs(dashboard_ids: Sequence[int]) -> tuple[DashboardRef, ...]:
    """Dashboard IDs and names for callers that already validated the dashboard IDs."""
    return _refs_in_given_order(dashboard_ids)


def create_dashboard(
    *,
    team_id: int,
    name: str,
    description: str = "",
    pinned: bool = False,
    variables: dict[str, Any] | None = None,
) -> DashboardRef:
    """Create an empty dashboard as the system, with no access check, for code that seeds a project."""
    dashboard = Dashboard.objects.create(
        team_id=team_id,
        name=name,
        description=description,
        pinned=pinned,
        variables=variables if variables is not None else {},
    )
    return DashboardRef(id=dashboard.id, name=dashboard.name)


def add_insight_tile(
    *, dashboard_id: int, insight_id: int, layouts: dict[str, Any] | None = None, color: str | None = None
) -> int:
    """Place an insight on a dashboard as the system, with no access check, and return the tile's id."""
    tile = DashboardTile.objects.create(
        dashboard_id=dashboard_id, insight_id=insight_id, layouts=layouts or {}, color=color
    )
    return tile.id


def _to_summary(dashboard: Dashboard) -> DashboardSummary:
    return DashboardSummary(
        id=dashboard.id,
        team_id=dashboard.team_id,
        name=dashboard.name,
        description=dashboard.description,
        created_at=dashboard.created_at,
        created_by_id=dashboard.created_by_id,
        deleted=dashboard.deleted,
        pinned=dashboard.pinned,
        creation_mode=DashboardCreationMode(dashboard.creation_mode),
        last_accessed_at=dashboard.last_accessed_at,
        last_refresh=dashboard.last_refresh,
        filters=dashboard.filters or {},
        variables=dashboard.variables,
    )


def _team_dashboards(team_id: int, *, include_deleted: bool) -> QuerySet[Dashboard]:
    # `team_id=` goes through the root-team filter, so an environment's id finds its project's dashboards.
    manager = Dashboard.objects_including_soft_deleted if include_deleted else Dashboard.objects
    return manager.filter(team_id=team_id)


def get_dashboard(*, team_id: int, dashboard_id: int, include_deleted: bool = False) -> DashboardSummary | None:
    """One dashboard of this team, or None. A soft-deleted dashboard counts only with `include_deleted`.

    Does not check object-level access: pass `summary.access_ref` to the caller's access check.
    """
    dashboard = _team_dashboards(team_id, include_deleted=include_deleted).filter(pk=dashboard_id).first()
    return _to_summary(dashboard) if dashboard is not None else None


def get_dashboards(
    *, team_id: int, dashboard_ids: Collection[int], include_deleted: bool = False
) -> dict[int, DashboardSummary]:
    """The dashboards of this team among these ids, keyed by id. Ids that match none are left out."""
    dashboards = _team_dashboards(team_id, include_deleted=include_deleted).filter(id__in=dashboard_ids)
    return {dashboard.id: _to_summary(dashboard) for dashboard in dashboards}


def live_dashboard_ids(*, team_id: int, dashboard_ids: Collection[int]) -> set[int]:
    """Which of these ids are a live dashboard of this team."""
    return set(
        _team_dashboards(team_id, include_deleted=False).filter(id__in=dashboard_ids).values_list("id", flat=True)
    )


def _filter_viewable(dashboards: QuerySet[Dashboard], user_access_control: UserAccessControl) -> QuerySet[Dashboard]:
    """Keep the dashboards the user may view, judged by the rules of the team that stores them.

    `_team_dashboards` finds an environment's dashboards on its project's root team, and access
    rules are per team, so the check has to read the root team's rules, not the environment's.
    """
    owner_team_id = dashboards.order_by().values_list("team_id", flat=True).first()
    if owner_team_id is None:
        return dashboards
    owner_access = user_access_control.for_team_ids([owner_team_id]).get(owner_team_id)
    if owner_access is None:
        return dashboards.none()
    return owner_access.filter_queryset_by_access_level(dashboards)


def viewable_dashboard_ids(
    *, team_id: int, dashboard_ids: Collection[int], user_access_control: UserAccessControl
) -> set[int]:
    """Which of these ids are a live dashboard of this team that the user may view."""
    dashboards = _team_dashboards(team_id, include_deleted=False).filter(id__in=dashboard_ids)
    return set(_filter_viewable(dashboards, user_access_control).values_list("id", flat=True))


def recently_accessed_dashboards(
    *, team_id: int, limit: int, user_access_control: UserAccessControl | None = None
) -> list[DashboardSummary]:
    """This team's live dashboards that someone has opened, most recently opened first.

    With `user_access_control`, only the dashboards that user may view count towards the limit.
    """
    dashboards = _team_dashboards(team_id, include_deleted=False).filter(last_accessed_at__isnull=False)
    if user_access_control is not None:
        dashboards = _filter_viewable(dashboards, user_access_control)
    return [_to_summary(dashboard) for dashboard in dashboards.order_by("-last_accessed_at")[:limit]]


def dashboard_access_ref(*, team_id: int, dashboard_id: int) -> ObjectAccessRef | None:
    """What object-level access control reads from a live dashboard stored on this team, or None.

    None too when the id finds a dashboard of the environment's project: a ref is checked against
    one team's rules, and those rules belong to the project's team. Use `can_access_dashboard` there.
    """
    summary = get_dashboard(team_id=team_id, dashboard_id=dashboard_id)
    return summary.access_ref if summary is not None and summary.team_id == team_id else None


def can_access_dashboard(
    dashboard: DashboardSummary,
    *,
    user_access_control: UserAccessControl,
    required_level: AccessControlLevel = "viewer",
) -> bool:
    """Whether the user has `required_level` on this dashboard, judged by the rules of the dashboard's own team.

    The dashboard may live on the project's team while `user_access_control` is bound to one of its
    environments; the check reads the dashboard's team either way.
    """
    return not user_access_control.denied_object_ids(
        "dashboard", [(str(dashboard.id), dashboard.team_id, dashboard.created_by_id)], required_level
    )


def insight_tiles(*, dashboard_id: int) -> list[DashboardInsightTileSummary]:
    """The live tiles of a dashboard that place a live insight, oldest tile first.

    An empty list when the dashboard is soft-deleted.
    """
    # The caller resolved this id through a team-scoped dashboard lookup first.
    # nosemgrep: idor-lookup-without-team
    tiles = DashboardTile.objects.filter(
        dashboard_id=dashboard_id, insight_id__isnull=False, insight__deleted=False
    ).order_by("id")
    return [
        DashboardInsightTileSummary(
            id=tile.id,
            dashboard_id=tile.dashboard_id,
            insight_id=tile.insight_id,
            layouts=tile.layouts or {},
            filters_overrides=tile.filters_overrides,
            group_key=tile.group_key or None,
        )
        for tile in tiles
        if tile.insight_id is not None
    ]


def tile_groups(*, team_id: int, dashboard_id: int) -> list[DashboardTileGroupSummary]:
    """The tile groups of a dashboard that hold a live tile, in the order the dashboard shows them.

    A group sits where its top-left tile is. Empty when the dashboard has no grouped tiles or is not this team's.
    """
    return tiles_logic.tile_groups(team_id=team_id, dashboard_id=dashboard_id)


def tile_filters_overrides(*, dashboard_id: int, insight_id: int) -> dict[str, Any] | None:
    """The filter overrides of the live tile that places this insight on this dashboard.

    None when there is no such tile, or the tile carries no overrides.
    """
    # The caller holds both ids from one of its own team-scoped rows.
    # nosemgrep: idor-lookup-without-team
    return (
        DashboardTile.objects.filter(dashboard_id=dashboard_id, insight_id=insight_id)
        .values_list("filters_overrides", flat=True)
        .first()
    )


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


def insight_ids_on_dashboards_accessed_since(*, team_ids: Collection[int], since: datetime) -> set[int]:
    """Insights with a live tile on a live dashboard of these teams that someone opened since the given time.

    One query. Any access counts: the app, the API, a shared link, or an embed.
    """
    if not team_ids:
        return set()
    return set(
        DashboardTile.objects.filter(
            dashboard__team_id__in=team_ids, dashboard__last_accessed_at__gte=since, insight_id__isnull=False
        )
        .values_list("insight_id", flat=True)
        .distinct()
    )


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


def check_insight_tile_limit(*, team: "Team", dashboard_id: int, dashboard_name: str | None, user: User) -> None:
    """Report a `resource limit hit` event when one more tile would put the dashboard at its insight limit.

    The limit only notifies, so the caller places the tile either way.
    """
    check_count_limit(
        team=team,
        key=LimitKey.MAX_INSIGHTS_PER_DASHBOARD,
        current_count=active_tile_count(dashboard_id),
        user=user,
        resource_properties={"dashboard_id": dashboard_id, "dashboard_name": dashboard_name or ""},
    )


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


def insight_ids_on_dashboard(dashboard_id: int, *, include_removed_tiles: bool = False) -> QuerySet:
    """Ids of the insights with a tile on this dashboard, as a subquery for `id__in`.

    With `include_removed_tiles`, a soft-deleted tile counts too, as it does in the `Insight.dashboards` relation.
    """
    manager = DashboardTile.objects_including_soft_deleted if include_removed_tiles else DashboardTile.objects
    # Filtering a list the caller has already scoped to its own team.
    # nosemgrep: idor-lookup-without-team
    return manager.filter(dashboard__id=dashboard_id).values_list("insight__id", flat=True).all()


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


def restore_tiles_for_insights_without_access_check(insight_ids: Collection[int]) -> None:
    """Re-activate every soft-deleted tile of these insights that sits on a live dashboard.

    For staff tooling that restores insights outside a user's access rules. Run inside the caller's
    transaction, like `restore_tiles_for_insights`.
    """
    DashboardTile.objects_including_soft_deleted.filter(
        insight_id__in=insight_ids, deleted=True, dashboard__deleted=False
    ).update(deleted=False)


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
        from posthog.api.sharing_publish_gate import check_can_add_insight_to_dashboard

        check_can_add_insight_to_dashboard(user, _to_summary(dashboard), query, user_access_control)
    return InsightTilePlacement(dashboards)


def _place_insight_tile(
    *,
    insight_id: int,
    insight_team_id: int,
    loaded_insight: "Insight | None",
    dashboard: Dashboard,
    query: Any,
    user: User,
    user_access_control: UserAccessControl | None,
    dashboard_access: UserAccessControl | None,
) -> tuple[DashboardTile, bool]:
    """Put the insight on one dashboard, and report whether it was missing from it before.

    `loaded_insight` is the insight row when the caller holds it, so that saving a new tile does
    not read the row again. `dashboard_access` is `user_access_control` resolved against the
    dashboard's own team; None skips the edit check. A removed tile is restored rather than
    duplicated, so it keeps its layout. An insight already on the dashboard returns its tile before
    any check, because nothing changes.
    """
    if dashboard.team_id != insight_team_id:
        raise DashboardNotFound

    live_tile = DashboardTile.objects.filter(insight_id=insight_id, dashboard=dashboard).first()
    if live_tile is not None:
        return live_tile, False

    # Adding a tile is an edit of the dashboard.
    if dashboard_access is not None and not dashboard_access.check_access_level_for_object(dashboard, "editor"):
        raise CannotAddToDashboard(dashboard.id)

    # The dashboard's public link or subscription must not expose a query the editor can't run.
    from posthog.api.sharing_publish_gate import check_can_add_insight_to_dashboard

    check_can_add_insight_to_dashboard(user, _to_summary(dashboard), query, user_access_control)

    insight_lookup: dict[str, Any] = (
        {"insight": loaded_insight} if loaded_insight is not None else {"insight_id": insight_id}
    )
    tile, created = DashboardTile.objects_including_soft_deleted.get_or_create(dashboard=dashboard, **insight_lookup)
    if tile.deleted:
        tile.deleted = False
        tile.save()
        return tile, True
    return tile, created


def add_insight_to_dashboard(
    *,
    insight_id: int,
    insight_team_id: int,
    query: Any,
    dashboard_id: int,
    user: User,
    user_access_control: UserAccessControl,
) -> PlacedInsightTile:
    """Place an existing insight on one dashboard, with the checks the insight API's `dashboards` field runs.

    `query` is the insight's stored query, for the shared-dashboard publish gate. An insight already
    on the dashboard keeps its tile and nothing changes. Refusals raise `CannotAddToDashboard`,
    `DashboardNotFound` or the publish gate's ValidationError.

    Run inside the caller's transaction.
    """
    dashboard = Dashboard.objects.filter(team_id=insight_team_id, pk=dashboard_id).first()
    if dashboard is None:
        raise DashboardNotFound(str(dashboard_id))
    live_tile = DashboardTile.objects.filter(insight_id=insight_id, dashboard=dashboard).first()
    if live_tile is not None:
        return PlacedInsightTile(id=live_tile.id, dashboard_id=dashboard.id, added=False)
    check_insight_tile_limit(team=dashboard.team, dashboard_id=dashboard.id, dashboard_name=dashboard.name, user=user)
    access_by_team = _dashboard_edit_access_by_team([dashboard], user_access_control)
    tile, added = _place_insight_tile(
        insight_id=insight_id,
        insight_team_id=insight_team_id,
        # A public facade function takes no product model, so this path saves the tile by insight ID.
        loaded_insight=None,
        dashboard=dashboard,
        query=query,
        user=user,
        user_access_control=user_access_control,
        dashboard_access=access_by_team[dashboard.team_id],
    )
    return PlacedInsightTile(id=tile.id, dashboard_id=dashboard.id, added=added)


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
        _place_insight_tile(
            insight_id=insight.id,
            insight_team_id=insight.team_id,
            loaded_insight=insight,
            dashboard=dashboard,
            query=query,
            user=user,
            user_access_control=user_access_control,
            dashboard_access=add_access_by_team.get(dashboard.team_id),
        )
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


# For callers outside this product that still query the dashboard models; parity tests pin each query.


def search_dashboards(
    *,
    project_id: int,
    query: str | None,
    access_control: UserAccessControl,
    limit: int,
    offset: int = 0,
    with_access_levels: bool = False,
    include_count: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Ranked full-text search over a project's dashboards, in the result shape of core search.

    Leaves out the dashboards the user may not view and the ones built from a template. Without a
    query the dashboards come in name order. `with_access_levels` adds `user_access_level`, the
    user's resolved level for each dashboard. `include_count=False` skips the count query and
    reports a total of 0.
    """
    rows, total_count = search_logic.search(
        project_id=project_id,
        query=query,
        access_control=access_control,
        limit=limit,
        offset=offset,
        include_count=include_count,
    )
    access_levels = (
        access_control.bulk_object_access_levels("dashboard", [(str(row["id"]), row["created_by_id"]) for row in rows])
        if with_access_levels
        else None
    )
    return to_search_results(
        rows, entity_type="dashboard", ranked=bool(query), access_levels=access_levels
    ), total_count


def dashboards_by_last_access(
    *, team_ids: list[int], user_access_control: UserAccessControl, limit: int
) -> list[DashboardSummary]:
    """These teams' live dashboards the user may view, most recently opened first.

    Dashboards nobody opened come last, newest first. Org admins see every dashboard.
    """
    if not team_ids:
        return []
    dashboards = usage_logic.by_last_access(team_ids=team_ids, user_access_control=user_access_control, limit=limit)
    return [_to_summary(dashboard) for dashboard in dashboards]


def find_dashboard_team_id(*, dashboard_id: int) -> int | None:
    """The team that stores a live dashboard, or None when there is no live dashboard with this id.

    Unscoped: only for a caller that checks the user's access to the returned team itself.
    """
    # nosemgrep: idor-lookup-without-team (the caller checks access to the returned team)
    return Dashboard.objects.filter(pk=dashboard_id).values_list("team_id", flat=True).first()


def home_tab_dashboard_id(*, team_id: int) -> int | None:
    """The dashboard this team's product analytics Home tab shows, or None for the built-in view.

    A dashboard that was soft-deleted since, or that another team stores, counts as none.
    """
    return team_settings_logic.home_tab_dashboard_id(team_id=team_id)


def set_home_tab_dashboard(*, team_id: int, dashboard_id: int | None) -> None:
    """Point this team's Home tab at a dashboard, or back at the built-in view with None.

    Does not check the dashboard: validate it against the team first, with `get_dashboard`.
    """
    team_settings_logic.set_home_tab_dashboard(team_id=team_id, dashboard_id=dashboard_id)


def remove_quick_filter_from_dashboards(*, team_id: int, quick_filter_id: str) -> int:
    """Take a deleted quick filter off every dashboard stored on this team, and return how many changed."""
    return team_settings_logic.remove_quick_filter_from_dashboards(team_id=team_id, quick_filter_id=quick_filter_id)


def placements_on_dashboards_accessed_since(
    *, placements: Collection[InsightPlacement], since: datetime, shared_only: bool = False
) -> list[InsightPlacement]:
    """Which of these placements have a live tile on a dashboard someone opened since the given time.

    With `shared_only`, the dashboard must also have an enabled sharing configuration. One query.
    """
    return tiles_logic.placements_on_dashboards_accessed_since(
        placements=placements, since=since, shared_only=shared_only
    )


def live_tile_placements(
    *, dashboard_ids: Collection[int] | None = None, insight_ids: Collection[int] | None = None
) -> list[TilePlacement]:
    """The live tiles on these dashboards, or of these insights, or both, oldest tile first.

    Live means neither the tile nor its dashboard is soft-deleted. A tile of a deleted insight still
    counts. Pass at least one of the two filters. Unscoped: the ids come from the caller's own rows.
    """
    return tiles_logic.live_tile_placements(dashboard_ids=dashboard_ids, insight_ids=insight_ids)


def insight_ids_on_template_dashboards(
    *, insight_ids: Collection[int], name_prefix: str, description_prefix: str
) -> set[int]:
    """Which of these insights have a live tile on a live dashboard built from a template, whose name
    and description start with these prefixes. Product-generated dashboards carry such prefixes."""
    return tiles_logic.insight_ids_on_template_dashboards(
        insight_ids=insight_ids, name_prefix=name_prefix, description_prefix=description_prefix
    )


def delete_widget_tiles_for_teams(team_ids: list[int]) -> None:
    """Delete every widget tile of these teams, soft-deleted ones included, without signals.

    Team deletion calls this before the Team row goes, because a tile protects its widget from the
    cascade.
    """
    tiles_logic.delete_widget_tiles_for_teams(team_ids)


def has_user_created_dashboard(*, team_id: int) -> bool:
    """Whether a person, not the system, created a live dashboard stored on this exact team.

    The project's dashboards are stored on its root team, so this is False for an environment.
    """
    return usage_logic.has_user_created_dashboard(team_id=team_id)


def dashboard_counts_by_team(count: DashboardUsageCount) -> dict[int, int]:
    """For the usage report: how many live dashboards of the given kind each team stores, keyed by team id.

    A shared dashboard counts once per enabled sharing configuration, and a tagged one once per tag.
    """
    return usage_logic.counts_by_team(count)


def dashboards_created_between(
    *, period_start: datetime, period_end: datetime, team_ids: range
) -> list[TeamDashboardRef]:
    """The live dashboards created after `period_start` and up to `period_end`, by teams in `team_ids`.

    Generated dashboards stay out. For cross-team batch jobs off the request path.
    """
    return usage_logic.created_between(period_start=period_start, period_end=period_end, team_ids=team_ids)


def create_global_template_if_missing(template: DashboardTemplateDefinition) -> bool:
    """Store a template every project can use, unless one with its name exists. True when it was created."""
    return templates_logic.create_global_template_if_missing(template)


def create_starter_dashboard(*, team_id: int) -> DashboardRef:
    """Create the pinned starter dashboard a new project gets, with the signup template's tiles.

    Run inside the caller's transaction. The caller makes it the team's primary dashboard.
    """
    dashboard = templates_logic.create_starter_dashboard(team_id=team_id)
    return DashboardRef(id=dashboard.id, name=dashboard.name)


def widget_type_label(widget_type: str) -> str | None:
    """The catalog label of a widget type, or None for a type the catalog does not list."""
    # Imported at call time: the catalog loads every widget spec, and they import posthog.schema.
    from products.dashboards.backend.widget_catalog import WIDGET_CATALOG  # noqa: PLC0415

    entry = WIDGET_CATALOG.get(widget_type)
    return entry["label"] if entry is not None else None


def hidden_dashboard_ids(
    *, team_id: int, dashboard_ids: Collection[int], user_access_control: UserAccessControl, include_deleted: bool
) -> set[int]:
    """Which of these dashboards of this team the user may not view. A soft-deleted one counts only with `include_deleted`.

    Without dashboard resource access, every dashboard is hidden except the ones granted to the user
    and the ones the user created. Org admins see every dashboard.
    """
    return visibility_logic.hidden_dashboard_ids(
        team_id=team_id,
        dashboard_ids=dashboard_ids,
        user_access_control=user_access_control,
        include_deleted=include_deleted,
    )


def insight_placements(
    *,
    team_id: int,
    dashboard_ids: Collection[int],
    include_deleted: bool,
    insight_ids: Collection[int] | None = None,
) -> list[InsightPlacement]:
    """The insight tiles on these dashboards of this team, oldest tile first. With `insight_ids`, only those insights.

    Without `include_deleted`, a removed tile and a tile on a soft-deleted dashboard do not count.
    A tile of a soft-deleted insight counts either way.
    """
    return tiles_logic.insight_placements(
        team_id=team_id, dashboard_ids=dashboard_ids, insight_ids=insight_ids, include_deleted=include_deleted
    )


__all__ = [
    "CannotAddToDashboard",
    "CannotRemoveFromDashboard",
    "DashboardInsightTile",
    "DashboardInsightTileSummary",
    "DashboardInsights",
    "DashboardNotEditable",
    "DashboardNotFound",
    "DashboardNotViewable",
    "DashboardRef",
    "DashboardSummary",
    "InsightTilePlacement",
    "MembershipChange",
    "PlacedInsightTile",
    "active_tile_count",
    "can_access_dashboard",
    "add_insight_tile",
    "add_insight_to_dashboard",
    "check_insight_tile_limit",
    "create_dashboard",
    "create_dashboard_from_tiles",
    "dashboard_access_ref",
    "dashboard_exists",
    "dashboard_insight_tile",
    "dashboard_insights",
    "dashboard_refs",
    "dashboards_by_insight",
    "get_dashboard",
    "get_dashboards",
    "hide_tiles_for_insights",
    "home_dashboard_insights",
    "insight_has_listed_tile",
    "insight_ids_on_dashboard",
    "insight_ids_on_dashboards_accessed_since",
    "insight_tiles",
    "insights_with_dashboard_edit_access",
    "live_dashboard_ids",
    "live_tile_insight_ids",
    "plan_insight_tile_placement",
    "recently_accessed_dashboards",
    "restore_tiles_for_insights",
    "restore_tiles_for_insights_without_access_check",
    "tile_filters_overrides",
    "tile_for_insight_on_dashboard",
    "tile_for_render",
    "tile_ids_prefetch",
    "tile_permissions_prefetch",
    "unknown_dashboard_ids",
    "update_insight_dashboard_membership",
    "viewable_dashboard_id",
    "viewable_dashboard_ids",
    "viewable_dashboard_ref",
    "AppliedDashboard",
    "DashboardTemplateDefinition",
    "DashboardUsageCount",
    "InsightPlacement",
    "TeamDashboardRef",
    "TilePlacement",
    "create_global_template_if_missing",
    "create_starter_dashboard",
    "dashboard_counts_by_team",
    "dashboards_by_last_access",
    "dashboards_created_between",
    "delete_widget_tiles_for_teams",
    "find_dashboard_team_id",
    "has_user_created_dashboard",
    "hidden_dashboard_ids",
    "home_tab_dashboard_id",
    "insight_ids_on_template_dashboards",
    "insight_placements",
    "live_tile_placements",
    "placements_on_dashboards_accessed_since",
    "remove_quick_filter_from_dashboards",
    "search_dashboards",
    "set_home_tab_dashboard",
    "widget_type_label",
]
