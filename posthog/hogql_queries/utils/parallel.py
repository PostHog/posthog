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

    Every worker gets its own copy of the context, so a `ContextVar.set` inside one worker cannot
    reach a sibling or the caller. Query tags depend on that isolation, because each worker tags
    its own ClickHouse queries.
    """
    jobs = [threading.Thread(target=contextvars.copy_context().run, args=(item,)) for item in work]
    for job in jobs:
        job.start()
    for job in jobs:
        job.join()
