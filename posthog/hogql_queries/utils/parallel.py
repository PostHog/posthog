"""Run query-runner work concurrently without dropping the caller's ambient context.

A bare `threading.Thread` starts with empty ContextVars, so everything the query path reads from
context is absent in the worker: the OpenTelemetry span context, the ClickHouse query tags, and the
warehouse-warning accumulator. Without the span context a worker opens its spans with no parent, so
one parallel insight reports several disconnected traces instead of a single request trace.
"""

import threading
import contextvars
from collections.abc import Callable, Sequence


def run_in_parallel_threads(work: Sequence[Callable[[], None]]) -> None:
    """Run each callable in its own thread, then wait for all of them.

    Every worker gets its own copy of the context mapping, so rebinding a ContextVar in one worker
    cannot reach a sibling or the caller. The copy is shallow, so a value reached through the
    context is still shared, and mutating one in place does reach the caller.

    Both halves are load-bearing. Query tags depend on the first, because `tag_queries` replaces the
    whole snapshot instead of mutating it, which keeps each worker's tags its own. Warehouse
    warnings depend on the second, because a worker contributes to the caller's accumulator.
    """
    jobs = [threading.Thread(target=contextvars.copy_context().run, args=(item,)) for item in work]
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
