import json
from typing import Any

from rest_framework import exceptions

from products.dashboards.backend.constants import RUN_INSIGHTS_DEFAULT_MAX_RESULT_CHARS, RUN_INSIGHTS_MAX_TOTAL_CHARS
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight

TRUNCATION_NOTE = (
    "[Truncated to {max_chars} characters. To read the whole table, run dashboard-insights-run again "
    "with tile_ids={tile_id} and max_result_chars=0.]"
)

BUDGET_NOTE = (
    "[Not run. The response reached its {budget} character budget. To read this tile, run "
    "dashboard-insights-run again with tile_ids={tile_id}.]"
)


def parse_tile_ids(raw: str | None) -> set[int] | None:
    """Parse the `tile_ids` query param. None means every tile on the dashboard."""
    if raw is None or not raw.strip():
        return None
    try:
        tile_ids = {int(part) for part in (part.strip() for part in raw.split(",")) if part}
    except ValueError as exc:
        raise exceptions.ValidationError("tile_ids must be a comma-separated list of integers.") from exc
    if not tile_ids:
        return None
    return tile_ids


def parse_max_result_chars(raw: str | None) -> int:
    """Parse the `max_result_chars` query param. Zero means no per-tile limit."""
    if raw is None or not raw.strip():
        return RUN_INSIGHTS_DEFAULT_MAX_RESULT_CHARS
    try:
        max_chars = int(raw)
    except ValueError as exc:
        raise exceptions.ValidationError("max_result_chars must be an integer.") from exc
    if max_chars < 0:
        raise exceptions.ValidationError("max_result_chars must be zero or greater.")
    return max_chars


def truncate_formatted_result(formatted: str, *, tile_id: int, max_chars: int) -> str:
    """Cut a formatted insight table to whole lines within the budget, and say so."""
    if max_chars <= 0 or len(formatted) <= max_chars:
        return formatted

    kept: list[str] = []
    used = 0
    for line in formatted.splitlines():
        used += len(line) + 1
        if used > max_chars:
            break
        kept.append(line)
    # A single row wider than the budget still has to be cut, or it defeats the bound.
    body = "\n".join(kept) if kept else formatted[:max_chars]
    return body + "\n" + TRUNCATION_NOTE.format(max_chars=max_chars, tile_id=tile_id)


def render_unsupported_result(result: Any) -> str:
    """Text for a result no LLM formatter covers, so `optimized` output stays bounded anyway."""
    return json.dumps(result, default=str)


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
