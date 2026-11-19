from collections.abc import Iterator
from contextlib import contextmanager

from posthog.hogql_queries.access_controlled_resources import shared_warehouse_lookups
from posthog.models.team import Team
from posthog.query_cache.read_history import batched_reads

from products.dashboards.backend.v2.flag import dashboard_v2_enabled


@contextmanager
def shared_tile_work(team: Team, distinct_id: str) -> Iterator[None]:
    """With `dashboard-v2` on, the tiles serialized inside the block share the work that is the same for
    every tile: warehouse name lookups for their cache keys, and the write that records their cache reads.
    Each tile's response is unchanged."""
    if not dashboard_v2_enabled(team, distinct_id):
        yield
        return
    with shared_warehouse_lookups(), batched_reads():
        yield
