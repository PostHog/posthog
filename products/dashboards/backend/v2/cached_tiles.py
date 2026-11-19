"""The `dashboard-v2` batched read: cached results for several insight tiles in one request.

It never runs a query. A tile with nothing cached comes back as a miss, to be loaded through the insight endpoint.
"""

from collections.abc import Callable, Collection, Sequence
from typing import Any

from django.db.models import TextChoices

import structlog

from posthog.api.services.query import PlannedQuery
from posthog.models.team import Team
from posthog.query_cache import prefetched_entries

from products.dashboards.backend.v2.first_load import shared_tile_work

logger = structlog.get_logger(__name__)


class CachedTileStatus(TextChoices):
    HIT = "hit", "Hit"
    MISS = "miss", "Miss"
    FORBIDDEN = "forbidden", "Forbidden"
    NOT_FOUND = "not_found", "Not found"


def read_cached_tiles(
    *,
    team: Team,
    distinct_id: str,
    tile_ids: Sequence[int],
    found_tile_ids: Collection[int],
    forbidden_tile_ids: Collection[int],
    plan_tile: Callable[[int], PlannedQuery | None],
    serialize_tile: Callable[[int], dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """One entry per requested tile ID, in request order, from one batched cache read and without running a query.
    Every reader of cached tiles goes through here, so they serve the same hits to the same people.
    The caller looks the tiles up and checks access. `plan_tile` and `serialize_tile` run the caller's serializer,
    which reads each tile's planned query from `context["planned_queries"]`."""
    readable_tile_ids = [
        tile_id for tile_id in tile_ids if tile_id in found_tile_ids and tile_id not in forbidden_tile_ids
    ]

    # Shares work across tiles as a dashboard load does: one set of warehouse lookups while the keys are
    # built, and one write that records every tile's cache read.
    with shared_tile_work(team, distinct_id):
        # Plan every viewable tile's query first, so all their entries come back from one cache read.
        planned_queries: dict[int, PlannedQuery] = {}
        for tile_id in readable_tile_ids:
            try:
                planned = plan_tile(tile_id)
                if planned is not None:
                    planned_queries[tile_id] = planned
            except Exception:
                # Left unplanned, the tile runs as it would without the batch, which reports the failure.
                logger.info("cached_tiles_plan_failed", tile_id=tile_id, exc_info=True)
        context["planned_queries"] = planned_queries
        cache_keys = [planned.cache_key for planned in planned_queries.values()]

        results: list[dict[str, Any]] = []
        # The serializer outlives the request in insight_result's lru_cache, so its context must not keep every
        # planned runner, and with it every tile's raw results, alive after this request.
        try:
            with prefetched_entries(cache_keys, team_id=team.pk):
                for tile_id in tile_ids:
                    if tile_id not in found_tile_ids:
                        results.append({"id": tile_id, "status": CachedTileStatus.NOT_FOUND})
                        continue
                    if tile_id in forbidden_tile_ids:
                        results.append({"id": tile_id, "status": CachedTileStatus.FORBIDDEN})
                        continue
                    insight_data = serialize_tile(tile_id)
                    if not insight_data.get("is_cached"):
                        results.append({"id": tile_id, "status": CachedTileStatus.MISS})
                        continue
                    results.append({"id": tile_id, "status": CachedTileStatus.HIT, "insight": insight_data})
        finally:
            context.pop("planned_queries", None)
    return results
