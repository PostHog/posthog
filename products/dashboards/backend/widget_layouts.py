from __future__ import annotations

from typing import Any

from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT
from products.dashboards.backend.widget_catalog import get_default_widget_layouts


def _column_heights(sm_layouts: list[dict[str, Any]]) -> list[int]:
    """Per-column bottom edge (max y + h). The overall dashboard bottom is ``max(...)``."""
    heights = [0] * DASHBOARD_GRID_COLUMN_COUNT
    for layout in sm_layouts:
        lx = max(0, int(layout.get("x", 0)))
        ly = int(layout.get("y", 0))
        lw = max(1, min(int(layout.get("w", 1)), DASHBOARD_GRID_COLUMN_COUNT))
        lh = max(1, int(layout.get("h", 1)))
        for column in range(lx, min(lx + lw, DASHBOARD_GRID_COLUMN_COUNT)):
            heights[column] = max(heights[column], ly + lh)
    return heights


def _find_bottom_row_placement(
    *,
    existing_sm_layouts: list[dict[str, Any]],
    pending_sm_layouts: list[dict[str, Any]] | None,
    width: int,
    height: int,
) -> dict[str, int]:
    """Place a widget at the bottom of the dashboard, anchored to the tallest column.

    The grid compacts vertically on render, so a tile only stays at the bottom if its
    column span includes the column that defines the bottom — otherwise compaction lifts
    it up into a shorter column's gap (the "lands in the middle" bug). Batch adds stack
    downward: each tile counts the previously placed ones (``pending_sm_layouts``), so the
    second lands below the first, and so on — a horizontal row can't survive compaction on
    a staircased dashboard.
    """
    w = max(1, min(width, DASHBOARD_GRID_COLUMN_COUNT))
    h = max(1, height)
    all_layouts = [*existing_sm_layouts, *(pending_sm_layouts or [])]

    heights = _column_heights(all_layouts)
    placement_y = max(heights)
    tallest_column = next(column for column, column_height in enumerate(heights) if column_height == placement_y)
    x = min(tallest_column, DASHBOARD_GRID_COLUMN_COUNT - w)
    return {"x": x, "y": placement_y, "w": w, "h": h}


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
