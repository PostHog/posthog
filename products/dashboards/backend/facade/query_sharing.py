"""Shared query execution for flagged dashboard refreshes, for the dashboard views."""

from collections.abc import AsyncIterator, Callable, Iterator, Sequence

from products.dashboards.backend import query_sharing_stream
from products.dashboards.backend.constants import MAX_CACHED_TILES_BATCH_SIZE
from products.dashboards.backend.facade.contracts import (
    DashboardQuerySharingCachedEvent,
    DashboardQuerySharingTileEvent,
)

__all__ = [
    "MAX_CACHED_TILES_BATCH_SIZE",
    "query_results_stream",
]


def query_results_stream(
    *,
    jobs: Sequence[Callable[[], DashboardQuerySharingTileEvent]],
    team_id: int,
    query_id: str,
    share_queries: bool,
    asynchronous: bool,
    debug_tile_ids: Sequence[int] = (),
    cached: DashboardQuerySharingCachedEvent | None = None,
) -> Iterator[bytes] | AsyncIterator[bytes]:
    """The dashboard query stream as SSE data frames: `cached` first when given, then one `tile` event per job in
    the order the jobs finish, then `complete`. A job that raises sends `error` in place of its tile, and a stream
    that gets no slot on this process sends one `error` and runs no job. Closing the iterator early cancels the
    queries that still run.

    With `share_queries`, compatible tile queries run as one shared query. A `cached` event makes this the board
    stream, which waits for the organization's query slots. `debug_tile_ids` names each job's tile, in job order,
    and adds that job's sharing decisions and ClickHouse work to its event. `query_id` prefixes each job's query
    id, for cancellation."""
    stream = query_sharing_stream.DashboardQuerySharingStream(
        jobs=jobs,
        team_id=team_id,
        query_id=query_id,
        debug_tile_ids=debug_tile_ids,
        cached=cached,
        share_queries=share_queries,
        kind="board" if cached is not None else "sharing",
    )
    return stream.astream() if asynchronous else stream.stream()
