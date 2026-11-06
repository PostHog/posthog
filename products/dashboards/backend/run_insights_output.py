import json
from typing import Any

from rest_framework import exceptions

from products.dashboards.backend.constants import (
    RUN_INSIGHTS_DEFAULT_MAX_RESULT_CHARS,
    RUN_INSIGHTS_MAX_TOTAL_CHARS,
    RUN_INSIGHTS_MAX_UNRUN_TILES,
    RUN_INSIGHTS_MIN_TILE_CHARS,
)
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

ELISION_NOTE = (
    "[{omitted} of {total} rows omitted here. To read the whole table, run dashboard-insights-run "
    "with tile_ids={tile_id} and max_result_chars=0.]"
)

CUT_NOTE = (
    "[Cut at {max_chars} characters. To read the whole table, run dashboard-insights-run with "
    "tile_ids={tile_id} and max_result_chars=0.]"
)

BUDGET_NOTE = (
    "[Not run. The response reached its {budget} character budget. To read this tile, run "
    "dashboard-insights-run again with tile_ids={tile_id}.]"
)

UNLISTED_NOTE = " [{unlisted} further tiles are not listed. Read the dashboard for their IDs.]"


def parse_tile_ids(raw: str | None) -> list[int]:
    """Parse the `tile_ids` query param into ordered, deduplicated IDs. Empty means the param was
    not given, which each caller reads its own way."""
    if raw is None or not raw.strip():
        return []
    try:
        tile_ids = [int(part) for part in (part.strip() for part in raw.split(",")) if part]
    except ValueError as exc:
        raise exceptions.ValidationError("tile_ids must be a comma-separated list of integers.") from exc
    return list(dict.fromkeys(tile_ids))


def parse_max_result_chars(raw: str | None) -> int:
    """Parse the `max_result_chars` query param. Zero means no per-tile limit.

    A budget below the floor is rejected rather than served, because a tile that cannot hold its
    truncation marker would have to either overrun the budget or drop the marker, and a caller
    that cannot see data was dropped reads a cut table as the whole one.
    """
    if raw is None or not raw.strip():
        return RUN_INSIGHTS_DEFAULT_MAX_RESULT_CHARS
    try:
        max_chars = int(raw)
    except ValueError as exc:
        raise exceptions.ValidationError("max_result_chars must be an integer.") from exc
    if max_chars < 0:
        raise exceptions.ValidationError("max_result_chars must be zero or greater.")
    if 0 < max_chars < RUN_INSIGHTS_MIN_TILE_CHARS:
        raise exceptions.ValidationError(
            f"max_result_chars must be {RUN_INSIGHTS_MIN_TILE_CHARS} or greater, or zero for the whole table."
        )
    return max_chars


def tile_fits_response_budget(used_chars: int) -> bool:
    """Whether the response has enough budget left for another tile to carry usable rows.
    Below the floor a tile yields a sliced header and a marker, so it is reported as not run."""
    return RUN_INSIGHTS_MAX_TOTAL_CHARS - used_chars >= RUN_INSIGHTS_MIN_TILE_CHARS


def tile_budget(max_result_chars: int, used_chars: int) -> int:
    """Per-tile budget, held down to what the response has left. Zero stays unbounded."""
    if max_result_chars <= 0:
        return 0
    return min(max_result_chars, RUN_INSIGHTS_MAX_TOTAL_CHARS - used_chars)


def bound_formatted_result(formatted: str, *, tile_id: int, max_chars: int) -> str:
    """Hold a formatted insight table inside `max_chars`, keeping both ends of it.

    Rows come out of the middle because which end carries the answer depends on the query type.
    A trends table runs oldest bucket first, so its recent data is at the bottom, while a funnel
    runs first step first and a paths table runs most-travelled first. Dropping the tail would
    hand an agent the opening of a date range and read as the whole of it.

    The marker counts against `max_chars`, so the result never grows past it. That holds for
    every budget the API accepts, because `parse_max_result_chars` rejects one too small to
    hold a marker.
    """
    if max_chars <= 0 or len(formatted) <= max_chars:
        return formatted

    lines = formatted.splitlines()
    # Both counts are at most the line count, so this reserves the widest the marker can render.
    marker_room = len(ELISION_NOTE.format(omitted=len(lines), total=len(lines), tile_id=tile_id)) + 1
    rows_budget = max_chars - marker_room

    if len(lines) < 3 or len(lines[0]) + 1 > rows_budget:
        # No middle to drop, or the header does not fit, so cutting the text is what holds the bound.
        cut_note = CUT_NOTE.format(max_chars=max_chars, tile_id=tile_id)
        return formatted[: max(max_chars - len(cut_note) - 1, 0)] + "\n" + cut_note

    # The first line is the column header in every formatter, so it is always kept.
    head = [lines[0]]
    tail: list[str] = []
    used = len(lines[0]) + 1
    next_head, next_tail = 1, len(lines) - 1

    while next_head <= next_tail:
        took = False
        # The tail goes first so an odd row count spends its last row on the recent end. Each pass
        # tries both ends, so one long row cannot stop the other end from filling.
        for from_tail in (True, False):
            if next_head > next_tail:
                break
            line = lines[next_tail] if from_tail else lines[next_head]
            if used + len(line) + 1 > rows_budget:
                continue
            used += len(line) + 1
            if from_tail:
                tail.append(line)
                next_tail -= 1
            else:
                head.append(line)
                next_head += 1
            took = True
        if not took:
            break

    note = ELISION_NOTE.format(omitted=next_tail - next_head + 1, total=len(lines) - 1, tile_id=tile_id)
    return "\n".join([*head, note, *reversed(tail)])


def render_unsupported_result(result: Any) -> str:
    """Text for a result no LLM formatter covers, so `optimized` output stays bounded anyway."""
    return json.dumps(result, default=str)


def unrun_tile_results(remaining: list[tuple[int, DashboardTile, Insight]]) -> list[dict[str, Any]]:
    """Markers for the tiles the response budget left out.

    The list is capped because it grows with the dashboard, and a few hundred markers would cost
    more than the budget they report. The last marker says how many tiles it leaves off, so a
    caller is never left thinking the dashboard ends there.
    """
    listed = remaining[:RUN_INSIGHTS_MAX_UNRUN_TILES]
    results = [unrun_tile_result(tile, insight, order) for order, tile, insight in listed]
    unlisted = len(remaining) - len(listed)
    if unlisted and results:
        results[-1]["insight"]["result"] += UNLISTED_NOTE.format(unlisted=unlisted)
    return results


def unrun_tile_result(tile: DashboardTile, insight: Insight, order: int) -> dict[str, Any]:
    """Stand-in for a tile the response budget left out, shaped like a run tile."""
    return {
        "id": tile.id,
        "insight": {
            "id": insight.id,
            "short_id": insight.short_id,
            "name": insight.name,
            "derived_name": insight.derived_name,
            "result": BUDGET_NOTE.format(budget=RUN_INSIGHTS_MAX_TOTAL_CHARS, tile_id=tile.id),
        },
        "order": order,
        "last_refresh": None,
        "is_cached": False,
    }
