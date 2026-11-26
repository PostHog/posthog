from collections.abc import Iterator
from contextlib import contextmanager

from posthog.hogql_queries.access_controlled_resources import shared_warehouse_lookups
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import dashboard_v2_enabled
from posthog.query_cache.read_history import batched_reads


@contextmanager
def shared_tile_work(team: Team, user: User | None) -> Iterator[None]:
    """With `dashboard-v2` on, the tiles serialized inside the block share the work that is the same for
    every tile: warehouse name lookups for their cache keys, and the write that records their cache reads.
    Each tile's response is unchanged."""
    if not dashboard_v2_enabled(team, user):
        yield
        return
    with shared_warehouse_lookups(), batched_reads():
        yield
