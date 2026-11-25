"""Lets a query kind run inside a dashboards v2 query batch while `/query` keeps refusing it.

The batch enters `dashboard_v2_batch_scope()` around every place it plans or runs its targets. A runner that is
batch-only is refused by `get_query_runner` outside the scope, whoever the caller is. A ContextVar is per thread and per
task, so nothing outside the batch can see it set, and Celery workers never do.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Kinds whose runners only accept a caller inside the batch. A Celery worker would refuse them, so the batch refreshes
# these in its own thread.
DASHBOARD_V2_BATCH_ONLY_KINDS = frozenset({"TraceSpansQuery", "TraceSpansAggregationQuery"})

_in_dashboard_v2_batch: ContextVar[bool] = ContextVar("in_dashboard_v2_batch", default=False)


@contextmanager
def dashboard_v2_batch_scope() -> Iterator[None]:
    token = _in_dashboard_v2_batch.set(True)
    try:
        yield
    finally:
        _in_dashboard_v2_batch.reset(token)


def in_dashboard_v2_batch() -> bool:
    return _in_dashboard_v2_batch.get()
