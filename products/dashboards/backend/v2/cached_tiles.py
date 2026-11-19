"""The `dashboard-v2` batched read: cached results for several insight tiles in one request.

It never runs a query. A tile with nothing cached comes back as a miss, to be loaded through the insight endpoint.
"""

from collections.abc import Callable
from typing import Any, Protocol

from django.db.models import TextChoices

import structlog
from rest_framework import exceptions
from rest_framework.request import Request

from posthog.api.services.query import PlannedQuery
from posthog.hogql_queries.refresh_policy import refresh_param_present
from posthog.models.team import Team
from posthog.query_cache import prefetched_entries

from products.dashboards.backend.constants import MAX_CACHED_TILES_BATCH_SIZE
from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.run_insights_output import parse_tile_ids
from products.dashboards.backend.v2.first_load import shared_tile_work
from products.product_analytics.backend.facade.models import Insight

logger = structlog.get_logger(__name__)


class CachedTileStatus(TextChoices):
    HIT = "hit", "Hit"
    MISS = "miss", "Miss"
    FORBIDDEN = "forbidden", "Forbidden"
    NOT_FOUND = "not_found", "Not found"


class TileInsightSerializer(Protocol):
    def plan_tile_query(self, insight: Insight) -> PlannedQuery | None: ...

    def to_representation(self, instance: Insight) -> dict[str, Any]: ...


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
    team: Team,
    user: Any,
    dashboard: Dashboard,
    tile_ids: list[int],
    restricted_insight_levels: Callable[[list[tuple[DashboardTile, Insight]]], dict[int, str]],
    insight_serializer: TileInsightSerializer,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """One entry per requested tile ID, in request order, from one batched cache read and without running a query.
    Every reader of cached tiles goes through here, so they serve the same hits to the same people.
    `insight_serializer` must have been built with `context`: each tile is set on it as `dashboard_tile` before
    its insight is planned or serialized."""
    tiles_by_id = {
        tile.id: (tile, insight)
        for tile in DashboardTile.dashboard_queryset(dashboard.tiles.filter(id__in=tile_ids))
        if (insight := tile.insight) is not None and insight.query is not None
    }
    restricted_levels = restricted_insight_levels(list(tiles_by_id.values()))

    # Shares work across tiles as a dashboard load does: one set of warehouse lookups while the keys are
    # built, and one write that records every tile's cache read.
    with shared_tile_work(team, user):
        # Plan every viewable tile's query first, so all their entries come back from one cache read.
        planned_queries: dict[int, PlannedQuery] = {}
        for tile, insight in tiles_by_id.values():
            if tile.id in restricted_levels:
                continue
            context["dashboard_tile"] = tile
            try:
                planned = insight_serializer.plan_tile_query(insight)
                if planned is not None:
                    planned_queries[tile.id] = planned
            except Exception:
                # Left unplanned, the tile runs as it would without the batch, which reports the failure.
                logger.info("cached_tiles_plan_failed", tile_id=tile.id, exc_info=True)
        context["planned_queries"] = planned_queries
        cache_keys = [planned.cache_key for planned in planned_queries.values()]

        results: list[dict[str, Any]] = []
        # The serializer outlives the request in insight_result's lru_cache, so its context must not keep every
        # planned runner, and with it every tile's raw results, alive after this request.
        try:
            with prefetched_entries(cache_keys, team_id=team.pk):
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
        finally:
            context.pop("planned_queries", None)
    return results
