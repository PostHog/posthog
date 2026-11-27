"""Dashboard widget tiles: run plans, widget runs, batch adds and settings updates.

The checks raise DRF errors, as `widget_create` and `widget_access` do, so the API answers with the
same 400 and 403 bodies whichever caller reached them.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from django.db import router, transaction
from django.utils.timezone import now

import structlog
from pydantic import JsonValue
from rest_framework import serializers

from posthog.models.team import Team
from posthog.models.user import User
from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloOperation

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.contracts import (
    NewWidgetTile,
    UpdatedWidget,
    WidgetPatch,
    WidgetRun,
    WidgetRunRefusal,
    WidgetRunResult,
)
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_access import check_widget_tile_product_access
from products.dashboards.backend.widget_create import create_widget_tile
from products.dashboards.backend.widget_layouts import collect_dashboard_sm_layouts_for_dashboard
from products.dashboards.backend.widget_specs.configs import CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE
from products.dashboards.backend.widget_specs.registry import (
    EXPECTED_WIDGET_TYPES,
    WIDGET_SPECS,
    count_active_widget_filters,
    extract_widget_filters,
    get_widget_spec,
    validate_widget_config,
)

logger = structlog.get_logger(__name__)


def public_widget_config(widget_type: str, config: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    # Rows of a retired widget type can still exist, and nothing says which of their config keys are public.
    if widget_type not in EXPECTED_WIDGET_TYPES:
        return {}
    public_config = dict(config)
    if widget_type == CONVERSATIONS_RECENT_TICKETS_WIDGET_TYPE:
        public_config.pop("search", None)
    return public_config


def plan_widget_runs(*, dashboard_id: int, tile_ids: Sequence[int]) -> tuple[WidgetRun | WidgetRunRefusal, ...]:
    tiles_by_id = {
        tile.id: tile
        for tile in DashboardTile.objects.select_related("widget").filter(
            dashboard_id=dashboard_id, id__in=tile_ids, widget__isnull=False
        )
    }
    plans: list[WidgetRun | WidgetRunRefusal] = []
    for tile_id in tile_ids:
        tile = tiles_by_id.get(tile_id)
        if tile is None or tile.widget is None:
            plans.append(
                WidgetRunRefusal(tile_id=tile_id, widget_type=None, error="Tile not found or is not a widget tile.")
            )
            continue
        widget = tile.widget
        spec = get_widget_spec(widget.widget_type)
        if spec is None:
            plans.append(
                WidgetRunRefusal(
                    tile_id=tile_id,
                    widget_type=widget.widget_type,
                    error=f"Unknown widget type: {widget.widget_type}",
                )
            )
            continue
        plans.append(
            WidgetRun(
                tile_id=tile_id,
                widget_type=widget.widget_type,
                config=widget.config,
                required_scopes=spec.required_scopes,
            )
        )
    return tuple(plans)


def run_widget(*, team: Team, user: User, dashboard_id: int, run: WidgetRun) -> WidgetRunResult:
    with slo_operation(
        spec=SloSpec(
            distinct_id=str(user.distinct_id),
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.DASHBOARD_WIDGET_DELIVERY,
            team_id=team.id,
            resource_id=str(run.tile_id),
        ),
        properties={
            "widget_type": run.widget_type,
            "dashboard_id": dashboard_id,
            "tile_id": run.tile_id,
        },
    ) as slo:
        try:
            result = WIDGET_SPECS[run.widget_type].query_fn(team, run.config, user=user, include_total_count=False)
            return WidgetRunResult(tile_id=run.tile_id, widget_type=run.widget_type, result=result, error=None)
        except Exception as exc:
            logger.exception("dashboard_run_widgets_failed", tile_id=run.tile_id, widget_type=run.widget_type)
            slo.fail_with_error(exc)
            return WidgetRunResult(
                tile_id=run.tile_id,
                widget_type=run.widget_type,
                result=None,
                error="Widget query failed. Please try again later.",
            )


def create_widget_tiles(
    *,
    team_id: int,
    dashboard_id: int,
    user: User,
    user_access_control: UserAccessControl,
    tiles: Sequence[NewWidgetTile],
) -> list[int]:
    dashboard = Dashboard.objects.select_related("team").get(id=dashboard_id, team_id=team_id)
    with transaction.atomic():
        existing_sm_layouts = collect_dashboard_sm_layouts_for_dashboard(dashboard)
        pending_sm_layouts: list[dict[str, Any]] = []
        tile_ids: list[int] = []

        for new_tile in tiles:
            payload: dict[str, Any] = {
                "widget_type": new_tile.widget_type,
                "config": new_tile.config,
                "name": new_tile.name,
                "description": new_tile.description,
            }
            if new_tile.layouts is not None:
                payload["layouts"] = new_tile.layouts
            if new_tile.show_description is not None:
                payload["show_description"] = new_tile.show_description
            tile = create_widget_tile(
                dashboard=dashboard,
                user=user,
                user_access_control=user_access_control,
                payload=payload,
                existing_sm_layouts=existing_sm_layouts,
                pending_sm_layouts=pending_sm_layouts,
            )
            tile_ids.append(tile.id)
            sm_layout = tile.layouts.get("sm") if isinstance(tile.layouts, dict) else None
            if isinstance(sm_layout, dict):
                pending_sm_layouts.append(sm_layout)
    return tile_ids


def update_widget(
    *,
    team_id: int,
    widget_id: UUID,
    user: User,
    user_access_control: UserAccessControl,
    patch: WidgetPatch,
) -> UpdatedWidget:
    """Write the patch in the caller's transaction."""
    # Read from the writer, because the save below writes back every field this read loaded.
    widget = DashboardWidget.objects.for_team(team_id).using(router.db_for_write(DashboardWidget)).get(id=widget_id)
    check_widget_tile_product_access(widget, user_access_control)
    if patch.widget_type is not None and patch.widget_type != widget.widget_type:
        raise serializers.ValidationError({"widget": "widget_type cannot be changed."})

    previous_widget_filters = extract_widget_filters(widget.widget_type, widget.config)
    if "config" in patch.fields_set:
        if not isinstance(patch.config, dict):
            raise serializers.ValidationError({"config": "Config must be an object."})
        widget.config = validate_widget_config(widget.widget_type, {**widget.config, **patch.config})
    if "name" in patch.fields_set:
        widget.name = patch.name or None
    if "description" in patch.fields_set:
        widget.description = patch.description
    widget.last_modified_by = user
    widget.last_modified_at = now()
    widget.save()

    new_widget_filters = extract_widget_filters(widget.widget_type, widget.config)
    return UpdatedWidget(
        widget_type=widget.widget_type,
        filters_changed="config" in patch.fields_set and new_widget_filters != previous_widget_filters,
        filters_count=count_active_widget_filters(widget.widget_type, widget.config),
    )
