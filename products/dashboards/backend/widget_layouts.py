from __future__ import annotations

from typing import Any

from products.dashboards.backend.widget_catalog import get_default_widget_layouts

MAX_WIDGETS_BATCH_SIZE = 10


def _max_sm_layout_bottom(sm_layouts: list[dict[str, Any]]) -> int:
    max_bottom = 0
    for layout in sm_layouts:
        max_bottom = max(max_bottom, int(layout.get("y", 0)) + int(layout.get("h", 0)))
    return max_bottom


def stack_widget_layout_at_bottom(
    *,
    widget_type: str,
    existing_sm_layouts: list[dict[str, Any]],
    pending_sm_layouts: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, int]]:
    defaults = get_default_widget_layouts(widget_type)
    width = defaults["sm"]["w"]
    height = defaults["sm"]["h"]
    sm_layouts = [*existing_sm_layouts, *(pending_sm_layouts or [])]
    y = _max_sm_layout_bottom(sm_layouts)
    sm = {"x": 0, "y": y, "w": width, "h": height}
    return {"sm": sm, "xs": {**sm}}


def collect_dashboard_sm_layouts(dashboard_tiles: list[Any]) -> list[dict[str, Any]]:
    sm_layouts: list[dict[str, Any]] = []
    for tile in dashboard_tiles:
        layouts = tile.layouts if isinstance(tile.layouts, dict) else {}
        sm_layout = layouts.get("sm")
        if isinstance(sm_layout, dict):
            sm_layouts.append(sm_layout)
    return sm_layouts


def collect_dashboard_sm_layouts_for_dashboard(dashboard: Any) -> list[dict[str, Any]]:
    sm_layouts: list[dict[str, Any]] = []
    for layouts in dashboard.tiles.filter(deleted=False).values_list("layouts", flat=True):
        if isinstance(layouts, dict):
            sm_layout = layouts.get("sm")
            if isinstance(sm_layout, dict):
                sm_layouts.append(sm_layout)
    return sm_layouts
