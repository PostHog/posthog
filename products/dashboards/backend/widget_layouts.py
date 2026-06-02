from __future__ import annotations

from typing import Any

from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT
from products.dashboards.backend.widget_catalog import get_default_widget_layouts


def _rectangles_overlap(
    x1: int,
    y1: int,
    w1: int,
    h1: int,
    x2: int,
    y2: int,
    w2: int,
    h2: int,
) -> bool:
    return x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2


def _layout_overlaps_any(
    sm_layouts: list[dict[str, Any]],
    x: int,
    y: int,
    w: int,
    h: int,
) -> bool:
    for layout in sm_layouts:
        lx = int(layout.get("x", 0))
        ly = int(layout.get("y", 0))
        lw = max(1, min(int(layout.get("w", 1)), DASHBOARD_GRID_COLUMN_COUNT))
        lh = max(1, int(layout.get("h", 1)))
        if _rectangles_overlap(x, y, w, h, lx, ly, lw, lh):
            return True
    return False


def _dashboard_bottom_y(sm_layouts: list[dict[str, Any]]) -> int:
    bottom_y = 0
    for layout in sm_layouts:
        y = int(layout.get("y", 0))
        h = max(1, int(layout.get("h", 1)))
        bottom_y = max(bottom_y, y + h)
    return bottom_y


def _find_bottom_row_placement(
    *,
    existing_sm_layouts: list[dict[str, Any]],
    pending_sm_layouts: list[dict[str, Any]] | None,
    width: int,
    height: int,
) -> dict[str, int]:
    """Place a widget on the bottom row of the dashboard, packing batch adds horizontally."""
    w = max(1, min(width, DASHBOARD_GRID_COLUMN_COUNT))
    h = max(1, height)
    pending = pending_sm_layouts or []
    all_layouts = [*existing_sm_layouts, *pending]

    if pending:
        placement_y = int(pending[0].get("y", 0))
    else:
        placement_y = _dashboard_bottom_y(existing_sm_layouts)

    for x in range(0, DASHBOARD_GRID_COLUMN_COUNT - w + 1):
        if not _layout_overlaps_any(all_layouts, x, placement_y, w, h):
            return {"x": x, "y": placement_y, "w": w, "h": h}

    return {"x": 0, "y": placement_y, "w": w, "h": h}


def stack_widget_layout_at_bottom(
    *,
    widget_type: str,
    existing_sm_layouts: list[dict[str, Any]],
    pending_sm_layouts: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, int]]:
    defaults = get_default_widget_layouts(widget_type)
    width = defaults["sm"]["w"]
    height = defaults["sm"]["h"]
    sm = _find_bottom_row_placement(
        existing_sm_layouts=existing_sm_layouts,
        pending_sm_layouts=pending_sm_layouts,
        width=width,
        height=height,
    )
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
