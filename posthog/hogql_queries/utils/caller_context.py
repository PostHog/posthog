import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from django.db import connections

from posthog.settings import TEST

_T = TypeVar("_T")
_R = TypeVar("_R")

# Each worker may hold a Postgres connection while HogQL resolves team and property-definition
# rows; 8 keeps one request comfortably below the per-process pool while still collapsing wall
# time for the common few-item case. Bump only after measuring PG pressure under real concurrency.
DEFAULT_PARALLELISM_LIMIT = 8


def map_in_caller_context(
    fn: Callable[[_T], _R],
    items: Sequence[_T],
    *,
    max_workers: int = DEFAULT_PARALLELISM_LIMIT,
    thread_name_prefix: str = "caller_context",
) -> list[_R]:
    """`pool.map` each item in a thread pool, with the caller's contextvars carried into the workers.

    `ThreadPoolExecutor` workers don't inherit the submitting thread's contextvars, so the query tags
    (team_id, feature, trigger) set on the read path would be lost inside the pool, silently un-tagging
    every ClickHouse query the workers emit. A Context can't be entered concurrently, so each worker
    gets its own copy. Workers release their Postgres connection on the way out, since pool threads
    end with the call and Django connections are per thread.

    Runs serially under TEST: a worker's own Django connection can't see the test transaction's
    uncommitted rows, so it would resolve against an empty team.
    """
    if TEST or len(items) <= 1:
        return [fn(item) for item in items]

    def run(ctx: contextvars.Context, item: _T) -> _R:
        try:
            return ctx.run(fn, item)
        finally:
            connections.close_all()

    contexts = [contextvars.copy_context() for _ in items]
    with ThreadPoolExecutor(max_workers=min(len(items), max_workers), thread_name_prefix=thread_name_prefix) as pool:
        return list(pool.map(run, contexts, items))
