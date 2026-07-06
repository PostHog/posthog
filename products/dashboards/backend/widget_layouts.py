from __future__ import annotations

import json
from typing import Any

from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT
from products.dashboards.backend.widget_catalog import get_default_widget_layouts

# Fallback size for a tile that has no persisted layout. Matches the dominant frontend
# default (`tileLayouts.ts` 6×5) and the widget catalog default, so synthetic placements
# approximate the rendered height closely enough to keep new widgets below everything.
_DEFAULT_TILE_WIDTH = 6
_DEFAULT_TILE_HEIGHT = 5


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


def _pack_at_bottom(column_heights: list[int], width: int, height: int) -> dict[str, int]:
    """Lowest-segment greedy placement, mirroring the dirty-tile packing in
    ``frontend/src/scenes/dashboard/tileLayouts.ts``: pick the leftmost ``width``-wide
    segment with the lowest top, ties keeping the leftmost."""
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


def collect_dashboard_sm_layouts_for_dashboard(dashboard: Any) -> list[dict[str, Any]]:
    """Existing ``sm`` layouts, plus a synthetic bottom placement for every tile that has
    no persisted layout, so widget placement counts the dashboard's true rendered height.

    Tiles added to a dashboard without a layout (e.g. an insight added via the insight API)
    default to ``layouts = {}``; the frontend stacks them at the bottom on render but only
    persists that on a layout save. Reading only persisted ``sm`` layouts would under-count
    the height and drop new widgets into a mid-page gap (the "lands in the 2nd row" bug)."""
    sm_layouts: list[dict[str, Any]] = []
    layoutless_count = 0
    # `deleted` is nullable with no default, so live tiles carry NULL — `filter(deleted=False)`
    # would miss them (NULL never equals False). Exclude only explicit deletes.
    for layouts in dashboard.tiles.exclude(deleted=True).values_list("layouts", flat=True):
        if isinstance(layouts, str):
            try:
                layouts = json.loads(layouts)
            except (ValueError, TypeError):
                layouts = None
        sm_layout = layouts.get("sm") if isinstance(layouts, dict) else None
        if isinstance(sm_layout, dict):
            sm_layouts.append(sm_layout)
        else:
            layoutless_count += 1

    if layoutless_count == 0:
        return sm_layouts

    # Stack layout-less tiles at the bottom (mirroring the frontend) so they contribute
    # to the height a new widget is placed below.
    column_heights = _column_heights(sm_layouts)
    for _ in range(layoutless_count):
        placement = _pack_at_bottom(column_heights, _DEFAULT_TILE_WIDTH, _DEFAULT_TILE_HEIGHT)
        sm_layouts.append(placement)
        for column in range(placement["x"], placement["x"] + placement["w"]):
            column_heights[column] = placement["y"] + placement["h"]
    return sm_layouts
