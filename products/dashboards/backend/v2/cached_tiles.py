"""The `dashboard-v2` batched read: cached results for several insight tiles in one request.

It never runs a query. A tile with nothing cached comes back as a miss, to be loaded through the insight endpoint.
"""

from collections.abc import Callable
from typing import Any

from django.db.models import TextChoices

from rest_framework import exceptions, serializers
from rest_framework.request import Request

from posthog.hogql_queries.refresh_policy import refresh_param_present

from products.dashboards.backend.constants import MAX_CACHED_TILES_BATCH_SIZE
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.run_insights_output import parse_tile_ids


class CachedTileStatus(TextChoices):
    HIT = "hit", "Hit"
    MISS = "miss", "Miss"
    FORBIDDEN = "forbidden", "Forbidden"
    NOT_FOUND = "not_found", "Not found"


def requested_tile_ids(request: Request) -> list[int]:
    # Covers the body as well as the query string: `resolve_execution_mode` honors either.
    if refresh_param_present(request):
        raise exceptions.ValidationError({"refresh": "This endpoint only reads cached results."})
    tile_ids = parse_tile_ids(request.query_params.get("tile_ids"))
    if not tile_ids:
        raise exceptions.ValidationError({"tile_ids": "tile_ids is required."})
    if len(tile_ids) > MAX_CACHED_TILES_BATCH_SIZE:
        raise exceptions.ValidationError(
            {"tile_ids": f"Request at most {MAX_CACHED_TILES_BATCH_SIZE} tiles at a time."}
        )
    return tile_ids


def read_cached_tiles(
    *,
    dashboard: Dashboard,
    tile_ids: list[int],
    restricted_insight_levels: Callable[[list[tuple[DashboardTile, Any]]], dict[int, str]],
    insight_serializer: serializers.Serializer,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """One entry per requested tile ID, in request order. `insight_serializer` must have been built with
    `context`: each tile is set on it as `dashboard_tile` before its insight is serialized."""
    tiles_by_id = {
        tile.id: (tile, insight)
        for tile in DashboardTile.dashboard_queryset(dashboard.tiles.filter(id__in=tile_ids))
        if (insight := tile.insight) is not None and insight.query is not None
    }
    restricted_levels = restricted_insight_levels(list(tiles_by_id.values()))

    results: list[dict[str, Any]] = []
    for tile_id in tile_ids:
        tile_and_insight = tiles_by_id.get(tile_id)
        if tile_and_insight is None:
            results.append({"id": tile_id, "status": CachedTileStatus.NOT_FOUND})
            continue
        tile, insight = tile_and_insight
        if tile_id in restricted_levels:
            results.append({"id": tile_id, "status": CachedTileStatus.FORBIDDEN})
            continue
        context["dashboard_tile"] = tile
        insight_data = insight_serializer.to_representation(insight)
        if not insight_data.get("is_cached"):
            results.append({"id": tile_id, "status": CachedTileStatus.MISS})
            continue
        results.append({"id": tile_id, "status": CachedTileStatus.HIT, "insight": insight_data})
    return results
