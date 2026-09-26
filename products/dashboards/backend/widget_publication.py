from typing import Any

from django.shortcuts import get_object_or_404
from django.utils.timezone import now

from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.exceptions import Conflict
from posthog.models import Team, User
from posthog.user_permissions import UserPermissions

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.feature_flags import dashboard_widgets_enabled
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import check_widget_tile_product_access
from products.dashboards.backend.widget_create import create_widget_tile
from products.dashboards.backend.widget_layouts import collect_dashboard_sm_layouts_for_dashboard
from products.dashboards.backend.widget_registry import validate_widget_config


def referenced_notebook_snapshot_ids(*, team_id: int, snapshot_ids: list[str]) -> set[str]:
    return set(
        DashboardTile.objects.filter(
            team_id=team_id,
            dashboard__team_id=team_id,
            dashboard__deleted=False,
            widget__team_id=team_id,
            widget__widget_type="notebook_widget",
            widget__config__snapshotId__in=snapshot_ids,
        )
        .exclude(deleted=True)
        .values_list("widget__config__snapshotId", flat=True)
    )


class DashboardWidgetPublication:
    def __init__(self, *, team: Team, user: User, dashboard_id: int | None, tile_id: int | None) -> None:
        self.team = team
        self.user = user
        self.tile_id = tile_id
        self.access = UserAccessControl(user=user, team=team)
        if tile_id is not None:
            tile = get_object_or_404(DashboardTile, id=tile_id, team_id=team.id, dashboard__deleted=False)
            dashboard_id = tile.dashboard_id
        self.dashboard = get_object_or_404(Dashboard, id=dashboard_id, team_id=team.id, deleted=False)
        if not dashboard_widgets_enabled(team=team, user=user):
            raise ValidationError("Dashboard widgets are not enabled for this project.")
        if not UserPermissions(user, team).dashboard(
            self.dashboard
        ).can_edit or not self.access.check_access_level_for_object(self.dashboard, "editor"):
            raise PermissionDenied("You don't have edit permissions for this dashboard.")

    def publish(
        self,
        *,
        widget_type: str,
        config: dict[str, Any],
        name: str,
        expected_config: dict[str, Any] | None = None,
    ) -> None:
        """Attach results in the caller's transaction so a failed tile write rolls back its results too."""
        if self.tile_id is None:
            create_widget_tile(
                dashboard=self.dashboard,
                user=self.user,
                user_access_control=self.access,
                payload={"widget_type": widget_type, "config": config, "name": name},
                existing_sm_layouts=collect_dashboard_sm_layouts_for_dashboard(self.dashboard),
            )
            return
        tile = get_object_or_404(
            DashboardTile.objects.select_for_update(),
            id=self.tile_id,
            team_id=self.team.id,
            dashboard=self.dashboard,
            dashboard__deleted=False,
        )
        widget = get_object_or_404(
            DashboardWidget.objects.for_team(self.team.id).select_for_update(), id=tile.widget_id
        )
        check_widget_tile_product_access(widget, self.access)
        if (
            widget.widget_type != widget_type
            or expected_config is None
            or any(widget.config.get(key) != value for key, value in expected_config.items())
        ):
            raise Conflict("This widget changed during refresh. Reload the dashboard and try again.")
        widget.config = validate_widget_config(widget_type, {**widget.config, **config})
        widget.last_modified_by = self.user
        widget.last_modified_at = now()
        widget.save()


def publish_widget(
    *,
    team_id: int,
    user_id: int,
    dashboard_id: int | None,
    tile_id: int | None,
    widget_type: str,
    config: dict[str, Any],
    name: str,
    expected_config: dict[str, Any] | None = None,
) -> None:
    destination = DashboardWidgetPublication(
        team=Team.objects.get(id=team_id),
        user=User.objects.get(id=user_id),
        dashboard_id=dashboard_id,
        tile_id=tile_id,
    )
    destination.publish(widget_type=widget_type, config=config, name=name, expected_config=expected_config)
