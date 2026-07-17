from __future__ import annotations

from typing import Any

from rest_framework import serializers

from posthog.models.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl

from products.dashboards.backend.feature_flags import dashboard_widgets_enabled
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import check_widget_tile_product_access
from products.dashboards.backend.widget_registry import get_widget_registry_entry, validate_widget_config


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

    if get_widget_registry_entry(widget_type) is None:
        raise serializers.ValidationError({"widget_type": f"Unknown widget type: {widget_type}"})

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
    return widget_type, validated_config
