"""Reads and writes of cross-project dashboards and their tiles, mapped to contracts."""

from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q, QuerySet

from rest_framework import serializers

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.activity_logging.model_activity import get_was_impersonated

from products.cross_project_dashboards.backend.facade import contracts
from products.cross_project_dashboards.backend.logic.access import assert_can_reference_insight, visible_project_ids
from products.cross_project_dashboards.backend.models import CrossProjectDashboard, CrossProjectDashboardTile

DUPLICATE_TILE = "That insight is already on this dashboard."
# Bounds what one dashboard page can carry, since every page embeds each dashboard's tiles.
MAX_TILES_PER_DASHBOARD = 100
TOO_MANY_TILES = f"A dashboard holds at most {MAX_TILES_PER_DASHBOARD} tiles. Remove one before adding another."


# Layouts change on every drag, so only these tile fields reach the activity log.
AUDITED_TILE_FIELDS = ("color", "filters_overrides")


def _tile_reference(tile: CrossProjectDashboardTile) -> dict[str, str]:
    # Any organization member can read the activity log, so the entry names the tile only. The
    # project, the insight and the filter values stay hidden from members denied that project.
    return {"tile_id": str(tile.id)}


def _log_tile_change(dashboard: CrossProjectDashboard, user: User, change: Change) -> None:
    # Tiles are written through their own endpoint, so the dashboard's model receiver never sees
    # them. Each change is logged on the parent dashboard so it shows in that dashboard's history.
    log_activity(
        organization_id=dashboard.organization_id,
        team_id=None,
        user=user,
        was_impersonated=get_was_impersonated(),
        item_id=dashboard.id,
        scope="CrossProjectDashboard",
        activity="updated",
        detail=Detail(name=dashboard.name, changes=[change]),
        # Written inside the tile's transaction, so a failed audit insert rolls the tile change back.
        strict=True,
    )


def _to_tile(tile: CrossProjectDashboardTile) -> contracts.CrossProjectTile:
    if not tile.project_exists:  # type: ignore[attr-defined]
        # Nobody can open a project that is gone, so nobody may read what was saved for it. That
        # includes the members who were denied the project before it was deleted or moved out of
        # the organization. The tile keeps only what the dashboard needs to place and remove it.
        return contracts.CrossProjectTile(
            id=tile.id,
            project_id=tile.project_id,
            insight_id=tile.insight_id,
            layouts=tile.layouts or {},
            color=None,
            filters_overrides={},
        )
    return contracts.CrossProjectTile(
        id=tile.id,
        project_id=tile.project_id,
        insight_id=tile.insight_id,
        layouts=tile.layouts or {},
        color=tile.color,
        filters_overrides=tile.filters_overrides or {},
    )


def _creator(dashboard: CrossProjectDashboard) -> contracts.DashboardCreator | None:
    creator = dashboard.created_by
    if creator is None:
        return None
    return contracts.DashboardCreator(id=creator.id, first_name=creator.first_name, email=creator.email)


def _to_summary(dashboard: CrossProjectDashboard) -> contracts.CrossProjectDashboardSummary:
    return contracts.CrossProjectDashboardSummary(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        filters=dashboard.filters or {},
        tile_count=dashboard.visible_tile_count,  # type: ignore[attr-defined]
        project_count=dashboard.visible_project_count,  # type: ignore[attr-defined]
        created_by=_creator(dashboard),
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def _to_dashboard(dashboard: CrossProjectDashboard) -> contracts.CrossProjectDashboard:
    return contracts.CrossProjectDashboard(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        filters=dashboard.filters or {},
        # Filled by the visible_tiles prefetch, so the reader never sees a tile they cannot open.
        tiles=[_to_tile(tile) for tile in dashboard.visible_tiles],  # type: ignore[attr-defined]
        created_by=_creator(dashboard),
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def _existing_projects(organization_id: UUID | str) -> QuerySet[Team, dict[str, Any]]:
    return Team.objects.filter(organization_id=organization_id).values("id")


def _readable_tiles(organization_id: UUID | str, user: User) -> Q:
    """Tiles from projects the user can open, plus tiles whose project no longer exists.

    A deleted project names nothing anyone can open, so every member sees its tile as gone and can
    remove it. Hiding it would leave it on the dashboard for good.
    """
    return Q(project_id__in=visible_project_ids(user, organization_id)) | ~Q(
        project_id__in=_existing_projects(organization_id)
    )


def _readable_tile_rows(organization_id: UUID | str, user: User) -> QuerySet[CrossProjectDashboardTile]:
    # _to_tile reads project_exists, so every tile it maps must come from this queryset.
    return CrossProjectDashboardTile.objects.filter(_readable_tiles(organization_id, user), deleted=False).annotate(
        project_exists=Exists(_existing_projects(organization_id).filter(id=OuterRef("project_id")))
    )


def _dashboards(organization_id: UUID | str, user: User) -> QuerySet[CrossProjectDashboard]:
    tiles = _readable_tile_rows(organization_id, user).order_by("created_at", "id")
    return (
        CrossProjectDashboard.objects.filter(organization_id=organization_id, deleted=False)
        .select_related("created_by")
        .prefetch_related(Prefetch("tiles", queryset=tiles, to_attr="visible_tiles"))
        .order_by("-created_at", "-id")
    )


def _dashboard_row(organization_id: UUID | str, dashboard_id: UUID, user: User) -> CrossProjectDashboard:
    dashboard = _dashboards(organization_id, user).filter(id=dashboard_id).first()
    if dashboard is None:
        raise contracts.DashboardNotFoundError()
    return dashboard


def _assert_can_change(organization_id: UUID | str, dashboard: CrossProjectDashboard, user: User) -> None:
    # Reads hide the tiles from a project the user is denied, so writes must not let that user
    # rename, re-filter or delete those tiles for the readers who can see them.
    referenced = set(
        CrossProjectDashboardTile.objects.filter(dashboard=dashboard, deleted=False).values_list(
            "project_id", flat=True
        )
    )
    # A tile whose project was deleted protects nothing, so it never blocks a change.
    still_existing = set(
        Team.objects.filter(organization_id=organization_id, id__in=referenced).values_list("id", flat=True)
    )
    if not still_existing <= set(visible_project_ids(user, organization_id)):
        raise contracts.DashboardChangeDeniedError()


def _lock_for_change(organization_id: UUID | str, dashboard_id: UUID, user: User) -> CrossProjectDashboard:
    """Lock the dashboard row, then check the write rule. Call it inside transaction.atomic().

    The lock keeps a concurrent tile add from changing the set of projects between the check and
    the write.
    """
    dashboard = (
        CrossProjectDashboard.objects.select_for_update()
        .filter(id=dashboard_id, organization_id=organization_id, deleted=False)
        .first()
    )
    if dashboard is None:
        raise contracts.DashboardNotFoundError()
    _assert_can_change(organization_id, dashboard, user)
    return dashboard


def _tiles(organization_id: UUID | str, dashboard_id: UUID, user: User) -> QuerySet[CrossProjectDashboardTile]:
    # A reader denied a project does not learn which of its insights the dashboard references.
    return (
        _readable_tile_rows(organization_id, user)
        .filter(organization_id=organization_id, dashboard_id=dashboard_id, dashboard__deleted=False)
        .select_related("dashboard")
        .order_by("created_at", "id")
    )


def _tile_row(organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User) -> CrossProjectDashboardTile:
    tile = _tiles(organization_id, dashboard_id, user).filter(id=tile_id).first()
    if tile is None:
        raise contracts.TileNotFoundError()
    return tile


def _lock_tile_for_change(
    organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User
) -> tuple[CrossProjectDashboardTile, CrossProjectDashboard]:
    """Lock the dashboard, check the write rule, then read the tile again under that lock.

    Reading the tile after the lock means a tile another request removed while this one waited is
    a 404, not a write to a deleted row. Call it inside transaction.atomic().
    """
    _tile_row(organization_id, dashboard_id, tile_id, user)
    try:
        dashboard = _lock_for_change(organization_id, dashboard_id, user)
    except contracts.DashboardNotFoundError as error:
        raise contracts.TileNotFoundError() from error
    tile = _tiles(organization_id, dashboard_id, user).select_for_update(of=("self",)).filter(id=tile_id).first()
    if tile is None:
        raise contracts.TileNotFoundError()
    return tile, dashboard


def list_dashboards(*, organization_id: UUID | str, user: User, offset: int, limit: int) -> contracts.DashboardPage:
    readable = Q(tiles__project_id__in=visible_project_ids(user, organization_id)) | ~Q(
        tiles__project_id__in=_existing_projects(organization_id)
    )
    visible = Q(tiles__deleted=False) & readable
    dashboards = (
        CrossProjectDashboard.objects.filter(organization_id=organization_id, deleted=False)
        .select_related("created_by")
        .annotate(
            visible_tile_count=Count("tiles", filter=visible),
            visible_project_count=Count("tiles__project_id", filter=visible, distinct=True),
        )
        .order_by("-created_at", "-id")
    )
    page = dashboards[offset : offset + limit]
    return contracts.DashboardPage(results=[_to_summary(dashboard) for dashboard in page], count=dashboards.count())


def get_dashboard(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> contracts.CrossProjectDashboard:
    return _to_dashboard(_dashboard_row(organization_id, dashboard_id, user))


def create_dashboard(
    *, organization_id: UUID | str, user: User, dashboard: contracts.NewDashboard
) -> contracts.CrossProjectDashboard:
    created = CrossProjectDashboard.objects.create(
        organization_id=organization_id,
        created_by=user,
        name=dashboard.name,
        description=dashboard.description,
        filters=dashboard.filters,
    )
    return get_dashboard(organization_id=organization_id, dashboard_id=created.id, user=user)


def update_dashboard(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, changes: contracts.DashboardChanges
) -> contracts.CrossProjectDashboard:
    with transaction.atomic():
        dashboard = _lock_for_change(organization_id, dashboard_id, user)
        updated = [name for name in ("name", "description", "filters") if name in changes.fields]
        for name in updated:
            setattr(dashboard, name, getattr(changes, name))
        if updated:
            dashboard.save(update_fields=[*updated, "updated_at"])
    return get_dashboard(organization_id=organization_id, dashboard_id=dashboard_id, user=user)


def delete_dashboard(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> None:
    with transaction.atomic():
        dashboard = _lock_for_change(organization_id, dashboard_id, user)
        dashboard.deleted = True
        dashboard.save(update_fields=["deleted"])


def list_tiles(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, offset: int, limit: int
) -> contracts.TilePage:
    tiles = _tiles(organization_id, dashboard_id, user)
    page = tiles[offset : offset + limit]
    return contracts.TilePage(results=[_to_tile(tile) for tile in page], count=tiles.count())


def get_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User
) -> contracts.CrossProjectTile:
    return _to_tile(_tile_row(organization_id, dashboard_id, tile_id, user))


def create_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, tile: contracts.NewTile
) -> contracts.CrossProjectTile:
    live = CrossProjectDashboard.objects.filter(id=dashboard_id, organization_id=organization_id, deleted=False)
    if not live.exists():
        raise contracts.DashboardNotFoundError()
    assert_can_reference_insight(user, organization_id, tile.project_id, tile.insight_id)
    # The dashboard row is the lock, so two concurrent creates cannot both pass the tile ceiling.
    with transaction.atomic():
        dashboard = _lock_for_change(organization_id, dashboard_id, user)
        if (
            CrossProjectDashboardTile.objects.filter(dashboard=dashboard, deleted=False).count()
            >= MAX_TILES_PER_DASHBOARD
        ):
            raise serializers.ValidationError({"insight_id": TOO_MANY_TILES})
        try:
            # The savepoint keeps a duplicate from breaking the enclosing transaction.
            with transaction.atomic():
                created = CrossProjectDashboardTile.objects.create(
                    dashboard=dashboard,
                    organization_id=dashboard.organization_id,
                    created_by=user,
                    project_id=tile.project_id,
                    insight_id=tile.insight_id,
                    layouts=tile.layouts,
                    color=tile.color,
                    filters_overrides=tile.filters_overrides,
                )
        except IntegrityError as error:
            raise serializers.ValidationError({"insight_id": DUPLICATE_TILE}) from error
        _log_tile_change(
            dashboard,
            user,
            Change(type="CrossProjectDashboardTile", action="created", field="tiles", after=_tile_reference(created)),
        )
    return get_tile(organization_id=organization_id, dashboard_id=dashboard_id, tile_id=created.id, user=user)


def update_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User, changes: contracts.TileChanges
) -> contracts.CrossProjectTile:
    with transaction.atomic():
        tile, dashboard = _lock_tile_for_change(organization_id, dashboard_id, tile_id, user)
        updated = [name for name in ("layouts", "color", "filters_overrides") if name in changes.fields]
        before = {name: getattr(tile, name) for name in AUDITED_TILE_FIELDS}
        for name in updated:
            setattr(tile, name, getattr(changes, name))
        if updated:
            tile.save(update_fields=[*updated, "updated_at"])
        changed = [name for name in AUDITED_TILE_FIELDS if before[name] != getattr(tile, name)]
        if changed:
            _log_tile_change(
                dashboard,
                user,
                Change(
                    type="CrossProjectDashboardTile",
                    action="changed",
                    field="tiles",
                    after={**_tile_reference(tile), "changed_fields": changed},
                ),
            )
    return _to_tile(tile)


def delete_tile(*, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User) -> None:
    with transaction.atomic():
        tile, dashboard = _lock_tile_for_change(organization_id, dashboard_id, tile_id, user)
        tile.deleted = True
        tile.save(update_fields=["deleted"])
        _log_tile_change(
            dashboard,
            user,
            Change(type="CrossProjectDashboardTile", action="deleted", field="tiles", before=_tile_reference(tile)),
        )
