from __future__ import annotations

from typing import Any

from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT
from products.dashboards.backend.widget_catalog import get_default_widget_layouts


def _column_heights_from_sm_layouts(sm_layouts: list[dict[str, Any]]) -> list[int]:
    column_heights = [0] * DASHBOARD_GRID_COLUMN_COUNT
    for layout in sm_layouts:
        x = int(layout.get("x", 0))
        y = int(layout.get("y", 0))
        w = max(1, min(int(layout.get("w", 1)), DASHBOARD_GRID_COLUMN_COUNT))
        h = max(1, int(layout.get("h", 1)))
        x = max(0, min(x, DASHBOARD_GRID_COLUMN_COUNT - 1))
        for column in range(x, min(x + w, DASHBOARD_GRID_COLUMN_COUNT)):
            column_heights[column] = max(column_heights[column], y + h)
    return column_heights


def _find_lowest_segment_placement(
    *,
    column_heights: list[int],
    width: int,
    height: int,
) -> dict[str, int]:
    """Greedy lowest-segment packing from ``frontend/src/scenes/dashboard/tileLayouts.ts``."""
    w = max(1, min(width, DASHBOARD_GRID_COLUMN_COUNT))
    h = max(1, height)

    best_x = 0
    best_y = max(column_heights[0:w])
    for x in range(1, DASHBOARD_GRID_COLUMN_COUNT - w + 1):
        segment_top = max(column_heights[x : x + w])
        if segment_top < best_y:
            best_x = x
            best_y = segment_top

    return {"x": best_x, "y": best_y, "w": w, "h": h}


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
    column_heights = _column_heights_from_sm_layouts(sm_layouts)
    sm = _find_lowest_segment_placement(column_heights=column_heights, width=width, height=height)
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
