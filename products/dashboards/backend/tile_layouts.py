from __future__ import annotations

from typing import Any

from products.dashboards.backend.constants import DASHBOARD_GRID_COLUMN_COUNT

# Default sm sizes mirroring frontend/src/scenes/dashboard/tileLayouts.ts `calculateLayouts`.
DEFAULT_INSIGHT_TILE_WIDTH = 6
DEFAULT_INSIGHT_TILE_HEIGHT = 5
DEFAULT_TEXT_TILE_WIDTH = 2
DEFAULT_TEXT_TILE_HEIGHT = 2


def _column_heights(sm_layouts: list[dict[str, Any]]) -> list[int]:
    heights = [0] * DASHBOARD_GRID_COLUMN_COUNT
    for layout in sm_layouts:
        x = int(layout.get("x", 0))
        y = int(layout.get("y", 0))
        w = max(1, min(int(layout.get("w", 1)), DASHBOARD_GRID_COLUMN_COUNT))
        h = max(1, int(layout.get("h", 1)))
        for col in range(max(0, x), min(x + w, DASHBOARD_GRID_COLUMN_COUNT)):
            heights[col] = max(heights[col], y + h)
    return heights


def stack_tile_layout_at_bottom(
    *,
    existing_sm_layouts: list[dict[str, Any]],
    width: int = DEFAULT_INSIGHT_TILE_WIDTH,
    height: int = DEFAULT_INSIGHT_TILE_HEIGHT,
) -> dict[str, dict[str, int]]:
    """Place a tile into the lowest available grid segment, mirroring the greedy placement the
    frontend applies to tiles without a stored layout (``calculateLayouts`` in tileLayouts.ts)."""
    w = max(1, min(width, DASHBOARD_GRID_COLUMN_COUNT))
    h = max(1, height)
    heights = _column_heights(existing_sm_layouts)

    best_x = 0
    best_y = max(heights[0:w])
    for x in range(1, DASHBOARD_GRID_COLUMN_COUNT - w + 1):
        segment_top = max(heights[x : x + w])
        if segment_top < best_y:
            best_x = x
            best_y = segment_top

    sm = {"x": best_x, "y": best_y, "w": w, "h": h}
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
    # ``deleted`` is a nullable boolean and most tiles are created with NULL, so exclude
    # ``deleted=True`` instead of filtering ``deleted=False`` (which would skip NULL rows).
    for layouts in dashboard.tiles.exclude(deleted=True).values_list("layouts", flat=True):
        if isinstance(layouts, dict):
            sm_layout = layouts.get("sm")
            if isinstance(sm_layout, dict):
                sm_layouts.append(sm_layout)
    return sm_layouts
