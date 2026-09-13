from typing import Any

from posthog.api.tagged_item import current_tag_names

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile


def _tile_style(tile: DashboardTile) -> dict[str, Any]:
    return {
        "layouts": tile.layouts,
        "color": tile.color,
        "transparent_background": tile.transparent_background,
    }


def _tile_to_template_tile(tile: DashboardTile) -> dict[str, Any] | None:
    if tile.text is not None:
        return {"type": "TEXT", "body": tile.text.body, **_tile_style(tile)}
    if tile.insight is not None:
        return {
            "type": "INSIGHT",
            "name": tile.insight.name,
            "description": tile.insight.description or "",
            "query": tile.insight.query or tile.insight.query_from_filters,
            **_tile_style(tile),
        }
    if tile.button_tile is not None:
        return {
            "type": "BUTTON",
            "button_tile": {
                "url": tile.button_tile.url,
                "text": tile.button_tile.text,
                "placement": tile.button_tile.placement,
                "style": tile.button_tile.style,
            },
            **_tile_style(tile),
        }
    if tile.widget is not None:
        return {
            "type": "WIDGET",
            "widget_type": tile.widget.widget_type,
            "config": tile.widget.config,
            **_tile_style(tile),
        }
    return None


def dashboard_to_template_payload(dashboard: Dashboard) -> dict[str, Any]:
    """Describe a dashboard in the body that `create_from_template_json` accepts.

    The payload holds no team, user, dashboard, or insight ids, so a different PostHog instance can import it.
    Tiles still hold project-scoped references: the ids of the resources a widget points at, and the action ids,
    cohort ids, and warehouse table names inside an insight query. Those resolve against the target project, so
    the same id can select a different object there.
    """
    tiles = [_tile_to_template_tile(tile) for tile in DashboardTile.dashboard_queryset(dashboard.tiles.all())]
    return {
        "template_name": dashboard.name or "",
        "dashboard_description": dashboard.description or "",
        "dashboard_filters": dashboard.filters or {},
        "tags": sorted(current_tag_names(dashboard)),
        "tiles": [tile for tile in tiles if tile is not None],
        "variables": [],
    }
