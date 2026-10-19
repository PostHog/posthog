"""Facade for cross_project_dashboards. The only module other products and the presentation layer import."""

from typing import Any
from uuid import UUID

from posthog.models import User

from ..logic import dashboards
from ..logic.filters import validate_cross_project_filters as _validate_cross_project_filters
from . import contracts


def validate_cross_project_filters(filters: Any) -> dict[str, Any]:
    """Return the filters normalized, or raise ValidationError for a filter bound to one project."""
    return _validate_cross_project_filters(filters)


def list_dashboards(*, organization_id: UUID | str, user: User, offset: int, limit: int) -> contracts.DashboardPage:
    """One page of the organization's dashboards. Each counts only the tiles from projects the user can open."""
    return dashboards.list_dashboards(organization_id=organization_id, user=user, offset=offset, limit=limit)


def get_dashboard(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> contracts.CrossProjectDashboard:
    """Raises DashboardNotFoundError."""
    return dashboards.get_dashboard(organization_id=organization_id, dashboard_id=dashboard_id, user=user)


def create_dashboard(
    *, organization_id: UUID | str, user: User, dashboard: contracts.NewDashboard
) -> contracts.CrossProjectDashboard:
    return dashboards.create_dashboard(organization_id=organization_id, user=user, dashboard=dashboard)


def update_dashboard(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, changes: contracts.DashboardChanges
) -> contracts.CrossProjectDashboard:
    """Raises DashboardNotFoundError, or DashboardChangeDeniedError when a tile is in a project the user cannot open."""
    return dashboards.update_dashboard(
        organization_id=organization_id, dashboard_id=dashboard_id, user=user, changes=changes
    )


def delete_dashboard(*, organization_id: UUID | str, dashboard_id: UUID, user: User) -> None:
    """Soft-deletes the dashboard. Raises DashboardNotFoundError or DashboardChangeDeniedError."""
    dashboards.delete_dashboard(organization_id=organization_id, dashboard_id=dashboard_id, user=user)


def list_tiles(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, offset: int, limit: int
) -> contracts.TilePage:
    """One page of the dashboard's tiles from projects the user can open. Empty for a deleted dashboard."""
    return dashboards.list_tiles(
        organization_id=organization_id, dashboard_id=dashboard_id, user=user, offset=offset, limit=limit
    )


def get_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User
) -> contracts.CrossProjectTile:
    """Raises TileNotFoundError."""
    return dashboards.get_tile(organization_id=organization_id, dashboard_id=dashboard_id, tile_id=tile_id, user=user)


def create_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, user: User, tile: contracts.NewTile
) -> contracts.CrossProjectTile:
    """Raises DashboardNotFoundError, DashboardChangeDeniedError, or ValidationError when the user cannot view the insight."""
    return dashboards.create_tile(organization_id=organization_id, dashboard_id=dashboard_id, user=user, tile=tile)


def update_tile(
    *, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User, changes: contracts.TileChanges
) -> contracts.CrossProjectTile:
    """Raises TileNotFoundError or DashboardChangeDeniedError. A tile's project and insight never change."""
    return dashboards.update_tile(
        organization_id=organization_id, dashboard_id=dashboard_id, tile_id=tile_id, user=user, changes=changes
    )


def delete_tile(*, organization_id: UUID | str, dashboard_id: UUID, tile_id: UUID, user: User) -> None:
    """Soft-deletes the tile. Raises TileNotFoundError or DashboardChangeDeniedError."""
    dashboards.delete_tile(organization_id=organization_id, dashboard_id=dashboard_id, tile_id=tile_id, user=user)
