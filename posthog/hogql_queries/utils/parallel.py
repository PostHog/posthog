"""Run query-runner work concurrently without dropping the caller's ambient context.

A bare `threading.Thread` starts with empty ContextVars, so everything the query path reads from
context is absent in the worker: the OpenTelemetry span context, the ClickHouse query tags, and the
warehouse-warning accumulator. Without the span context a worker opens its spans with no parent, so
one parallel insight reports several disconnected traces instead of a single request trace.
"""

import threading
import contextvars
from collections.abc import Callable, Sequence

from posthog.clickhouse.query_tagging import get_query_tags, query_tags


def run_in_parallel_threads(work: Sequence[Callable[[], None]]) -> None:
    """Run each callable in its own thread, then wait for all of them.

    Every worker gets its own copy of the context mapping, so rebinding a ContextVar in one worker
    cannot reach a sibling or the caller. The copy is shallow, so a value reached through the
    context is still shared, and mutating one in place does reach the caller.

    Warehouse warnings depend on that shallow sharing, because a worker contributes to the
    caller's accumulator. Query tags do not: this helper gives each worker a private tags copy up
    front, so even a worker that mutates its tags in place (skipping `tag_queries`, which always
    replaces the snapshot instead) only ever touches its own copy, never a sibling's or the
    caller's.

    An exception raised by a work item no longer escapes to `threading`'s default exception hook
    (stderr) and vanishes — it is collected and re-raised in the caller once every thread has
    joined, so a raising item cannot leave the caller reading a partial result with no signal
    anything went wrong.
    """
    errors: list[Exception] = []

    def run_item(item: Callable[[], None]) -> None:
        # Rebind before running the item, not after: a worker's very first line of code could
        # mutate the shared QueryTags object in place, so the copy has to exist before that.
        query_tags.set(get_query_tags().model_copy())
        try:
            item()
        except Exception as e:
            errors.append(e)

    jobs = [
        threading.Thread(target=contextvars.copy_context().run, args=(run_item, item), name=f"parallel-work-{i}")
        for i, item in enumerate(work)
    ]
    started: list[threading.Thread] = []
    try:
        for job in jobs:
            job.start()
            started.append(job)
    finally:
        # Join whatever started, so a failure part way through the fan-out cannot leave workers
        # writing to the result lists the caller is about to abandon.
        for job in started:
            job.join()

    if errors:
        raise errors[0]
