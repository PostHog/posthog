"""Reads and writes of cross-project dashboards and their tiles, mapped to contracts."""

from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet

from rest_framework import serializers

from posthog.models import User

from products.cross_project_dashboards.backend.facade import contracts
from products.cross_project_dashboards.backend.logic.access import assert_can_reference_insight, visible_project_ids
from products.cross_project_dashboards.backend.models import CrossProjectDashboard, CrossProjectDashboardTile

DUPLICATE_TILE = "That insight is already on this dashboard."


def _to_tile(tile: CrossProjectDashboardTile) -> contracts.CrossProjectTile:
    return contracts.CrossProjectTile(
        id=tile.id,
        project_id=tile.project_id,
        insight_id=tile.insight_id,
        layouts=tile.layouts or {},
        color=tile.color,
        filters_overrides=tile.filters_overrides or {},
    )


def _to_dashboard(dashboard: CrossProjectDashboard) -> contracts.CrossProjectDashboard:
    creator = dashboard.created_by
    return contracts.CrossProjectDashboard(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        filters=dashboard.filters or {},
        # Filled by the visible_tiles prefetch, so the reader never sees a tile they cannot open.
        tiles=[_to_tile(tile) for tile in dashboard.visible_tiles],  # type: ignore[attr-defined]
        created_by=(
            contracts.DashboardCreator(id=creator.id, first_name=creator.first_name, email=creator.email)
            if creator
            else None
        ),
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def _dashboards(organization_id: UUID | str, user: User) -> QuerySet[CrossProjectDashboard]:
    visible = visible_project_ids(user, organization_id)
    tiles = CrossProjectDashboardTile.objects.filter(deleted=False, project_id__in=visible).order_by("created_at", "id")
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


def _tiles(organization_id: UUID | str, dashboard_id: UUID, user: User) -> QuerySet[CrossProjectDashboardTile]:
    # A reader denied a project does not learn which of its insights the dashboard references.
    return CrossProjectDashboardTile.objects.filter(
        organization_id=organization_id,
        dashboard_id=dashboard_id,
        dashboard__deleted=False,
        deleted=False,
        project_id__in=visible_project_ids(user, organization_id),
    ).order_by("created_at", "id")


def _tile_row(organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User) -> CrossProjectDashboardTile:
    tile = _tiles(organization_id, dashboard_id, user).filter(id=tile_id).first()
    if tile is None:
        raise contracts.TileNotFoundError()
    return tile


def list_dashboards(*, organization_id: UUID | str, user: User) -> list[contracts.CrossProjectDashboard]:
    return [_to_dashboard(dashboard) for dashboard in _dashboards(organization_id, user)]


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
    dashboard = _dashboard_row(organization_id, dashboard_id, user)
    updated = [name for name in ("name", "description", "filters") if name in changes.fields]
    for name in updated:
        setattr(dashboard, name, getattr(changes, name))
    if updated:
        dashboard.save(update_fields=[*updated, "updated_at"])
    return get_dashboard(organization_id=organization_id, dashboard_id=dashboard_id, user=user)


def delete_dashboard(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> None:
    dashboard = _dashboard_row(organization_id, dashboard_id, user)
    dashboard.deleted = True
    dashboard.save(update_fields=["deleted"])


def list_tiles(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> list[contracts.CrossProjectTile]:
    return [_to_tile(tile) for tile in _tiles(organization_id, dashboard_id, user)]


def get_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User
) -> contracts.CrossProjectTile:
    return _to_tile(_tile_row(organization_id, dashboard_id, tile_id, user))


def create_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, tile: contracts.NewTile
) -> contracts.CrossProjectTile:
    dashboard = CrossProjectDashboard.objects.filter(
        id=dashboard_id, organization_id=organization_id, deleted=False
    ).first()
    if dashboard is None:
        raise contracts.DashboardNotFoundError()
    assert_can_reference_insight(user, organization_id, tile.project_id, tile.insight_id)
    try:
        # The savepoint keeps a duplicate from breaking an enclosing transaction.
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
    return _to_tile(created)


def update_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User, changes: contracts.TileChanges
) -> contracts.CrossProjectTile:
    tile = _tile_row(organization_id, dashboard_id, tile_id, user)
    updated = [name for name in ("layouts", "color", "filters_overrides") if name in changes.fields]
    for name in updated:
        setattr(tile, name, getattr(changes, name))
    if updated:
        tile.save(update_fields=[*updated, "updated_at"])
    return _to_tile(tile)


def delete_tile(*, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User) -> None:
    tile = _tile_row(organization_id, dashboard_id, tile_id, user)
    tile.deleted = True
    tile.save(update_fields=["deleted"])
