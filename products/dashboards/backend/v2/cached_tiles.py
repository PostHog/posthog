"""The `dashboard-v2` batched read: cached results for several insight tiles in one request.

It never runs a query. A tile with nothing cached comes back as a miss, to be loaded through the insight endpoint.
"""

from collections.abc import Callable, Collection, Hashable, Iterator, Sequence
from contextlib import contextmanager
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

    with planned_cache_reads(team=team, distinct_id=distinct_id, keys=readable_tile_ids, plan=plan_tile) as planned:
        context["planned_queries"] = planned
        results: list[dict[str, Any]] = []
        # The serializer outlives the request in insight_result's lru_cache, so its context must not keep every
        # planned runner, and with it every tile's raw results, alive after this request.
        try:
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


@contextmanager
def planned_cache_reads[K: Hashable](
    *, team: Team, distinct_id: str, keys: Sequence[K], plan: Callable[[K], PlannedQuery | None]
) -> Iterator[dict[K, PlannedQuery]]:
    """Plans the query behind each key, then reads every planned cache entry in one round trip.
    Inside the block, a planned runner's cache lookup is served from that read. A key whose query fails to plan,
    or has no runner, is left out of the yielded dict."""
    # Shares work across queries as a dashboard load does: one set of warehouse lookups while the keys are
    # built, and one write that records every cache read.
    with shared_tile_work(team, distinct_id):
        planned_queries: dict[K, PlannedQuery] = {}
        for key in keys:
            try:
                planned = plan(key)
                if planned is not None:
                    planned_queries[key] = planned
            except Exception:
                # The caller decides what an unplanned key means: a tile runs as it would without the batch.
                logger.info("cached_tiles_plan_failed", key=key, exc_info=True)
        with prefetched_entries([planned.cache_key for planned in planned_queries.values()], team_id=team.pk):
            yield planned_queries
