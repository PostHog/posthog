"""Run query-runner work concurrently without dropping the caller's ambient context.

A bare `threading.Thread` starts with empty ContextVars, so everything the query path reads from
context is absent in the worker: the OpenTelemetry span context, the ClickHouse query tags, and the
warehouse-warning accumulator. Without the span context a worker opens its spans with no parent, so
one parallel insight reports several disconnected traces instead of a single request trace.

`ThreadPoolExecutor` drops the context the same way, so submitting a bare callable to a pool has
the same defect as the bare thread it replaces.
"""

import contextvars
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

import structlog

from posthog.hogql.constants import INSIGHT_QUERY_FANOUT_CONCURRENCY

from posthog.clickhouse.query_tagging import get_query_tags, query_tags

logger = structlog.get_logger(__name__)


def run_in_parallel_threads(
    work: Sequence[Callable[[], None]],
    *,
    max_workers: int = INSIGHT_QUERY_FANOUT_CONCURRENCY,
    thread_name_prefix: str = "parallel_work",
) -> None:
    """Run the callables in a bounded thread pool, then wait for all of them.

    The pool caps how many run at once. One insight request expands into one query per series, and
    a client controls that expansion, so an unbounded fan-out lets one request take a web worker's
    threads and a large share of the shared Postgres connection pool.

    Every worker gets its own copy of the context mapping, so rebinding a ContextVar in one worker
    cannot reach a sibling or the caller. The copy is shallow, so a value reached through the
    context is still shared, and mutating one in place does reach the caller.

    Warehouse warnings and the query scan accumulator depend on that shallow sharing, because a
    worker contributes to the caller's object. Query tags do not: this helper gives each worker a
    private tags copy up front, so even a worker that mutates its tags in place (skipping
    `tag_queries`, which always replaces the snapshot instead) only ever touches its own copy,
    never a sibling's or the caller's.

    An exception raised by a work item does not escape to the pool's future and vanish unread. It
    is collected and re-raised in the caller once every item has finished, so a raising item cannot
    leave the caller reading a partial result with no signal anything went wrong. If more than one
    item raises, the caller sees whichever exception is appended first, meaning the first item to
    finish raising rather than the first item in `work`, and every other collected exception is
    logged rather than dropped.
    """
    if not work:
        return

    errors: list[Exception] = []

    def run_item(item: Callable[[], None]) -> None:
        try:
            # Rebind before running the item, not after: a worker's very first line of code could
            # mutate the shared QueryTags object in place, so the copy has to exist before that.
            query_tags.set(get_query_tags().model_copy())
            item()
        except Exception as e:
            errors.append(e)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(work)), thread_name_prefix=thread_name_prefix) as executor:
        for item in work:
            # A fresh Context per item, because one Context cannot be entered twice and a pool
            # thread runs several items in turn.
            executor.submit(contextvars.copy_context().run, run_item, item)

    if errors:
        # Surface every secondary error with its traceback before re-raising the first, so a
        # concurrent failure doesn't disappear into the void. Matches funnels_query_runner's
        # `_run_in_parallel`.
        for dropped in errors[1:]:
            logger.exception("parallel_work_secondary_error", exc_info=dropped)
        raise errors[0]
