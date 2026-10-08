from __future__ import annotations

from typing import Any

from rest_framework import serializers

from posthog.models.team import Team
from posthog.models.user import User
from posthog.resource_limits import LimitKey, check_count_limit

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.feature_flags import dashboard_widgets_enabled, widget_flag_enabled
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import check_widget_tile_product_access
from products.dashboards.backend.widget_layouts import stack_widget_layout_at_bottom
from products.dashboards.backend.widget_registry import validate_widget_config
from products.dashboards.backend.widget_specs.configs import NOTEBOOK_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import get_widget_spec


def prepare_widget_tile_create(
    *,
    team: Team,
    widget_type: str,
    config: dict[str, Any],
    user: User | None = None,
    user_access_control: UserAccessControl | None = None,
) -> tuple[str, dict[str, Any]]:
    if not dashboard_widgets_enabled(team=team, user=user):
        raise serializers.ValidationError({"widget": "Dashboard widgets are not enabled for this project."})

    spec = get_widget_spec(widget_type)
    if spec is None:
        raise serializers.ValidationError({"widget_type": f"Unknown widget type: {widget_type}"})

    # Adds-only kill switch (already-placed tiles keep rendering when the flag is off).
    if spec.creation_flag and not widget_flag_enabled(spec.creation_flag, team=team, user=user):
        raise serializers.ValidationError({"widget_type": f"{spec.label} widgets are not enabled for this project."})

    if not isinstance(config, dict):
        raise serializers.ValidationError({"config": "Config must be an object."})

    if user_access_control is not None:
        probe_widget = DashboardWidget(
            widget_type=widget_type,
            config=config,
            team_id=team.id,
        )
        check_widget_tile_product_access(probe_widget, user_access_control)

    # team_id stays on probe_widget for RBAC; pydantic validation is shape-only — team
    # defaults (e.g. filterTestAccounts) resolve at query time in widgets/config.py.
    validated_config = validate_widget_config(widget_type, config)
    if widget_type == NOTEBOOK_WIDGET_TYPE and not validated_config.get("snapshotId"):
        raise serializers.ValidationError({"config": "Add this widget from a notebook to save its results first."})
    return widget_type, validated_config


def create_widget_tile(
    *,
    dashboard: Dashboard,
    user: User,
    user_access_control: UserAccessControl,
    payload: dict[str, Any],
    existing_sm_layouts: list[dict[str, Any]] | None = None,
    pending_sm_layouts: list[dict[str, Any]] | None = None,
) -> DashboardTile:
    widget_type = payload["widget_type"]
    config = payload["config"]
    normalized_widget_type, validated_config = prepare_widget_tile_create(
        team=dashboard.team,
        widget_type=widget_type,
        config=config,
        user=user,
        user_access_control=user_access_control,
    )
    check_count_limit(
        team=dashboard.team,
        key=LimitKey.MAX_WIDGETS_PER_DASHBOARD,
        current_count=dashboard.tiles.filter(widget_id__isnull=False).exclude(deleted=True).count(),
        user=user,
    )
    layouts = payload.get("layouts")
    if layouts is None:
        layouts = stack_widget_layout_at_bottom(
            widget_type=normalized_widget_type,
            existing_sm_layouts=existing_sm_layouts or [],
            pending_sm_layouts=pending_sm_layouts,
        )
    tile_defaults: dict[str, Any] = {
        "layouts": layouts,
    }
    if "show_description" in payload:
        tile_defaults["show_description"] = payload["show_description"]

    widget = DashboardWidget.objects.for_team(dashboard.team_id).create(
        team_id=dashboard.team_id,
        widget_type=normalized_widget_type,
        name=payload.get("name") or None,
        description=payload.get("description", ""),
        config=validated_config,
        created_by=user,
        last_modified_by=user,
    )
    return DashboardTile.objects.create(
        dashboard=dashboard,
        team_id=dashboard.team_id,
        widget=widget,
        **tile_defaults,
    )
