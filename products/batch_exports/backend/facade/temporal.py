"""
Temporal registration wiring for batch_exports.

Re-exports what core registers with Temporal: the worker bootstrap commands
(``start_temporal_worker``, ``start_temporal_workflow``, ``execute_temporal_workflow``)
take ``WORKFLOWS`` and ``ACTIVITIES``, and ``posthog/temporal/common/worker.py`` takes the
metrics interceptor.

Names resolve lazily (PEP 562), mirroring ``backend/temporal/__init__.py``. Eager imports
here would put every destination's vendor SDK (databricks, snowflake, bigquery, ...) on
the import path of anything that touches this facade, which the startup import budget
forbids — see ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from functools import cache
from typing import TYPE_CHECKING, Any

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

if TYPE_CHECKING:
    from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor
    from products.batch_exports.backend.temporal.workflows import ACTIVITIES, WORKFLOWS

_B = "products.batch_exports.backend.temporal."

_LAZY = {
    "ACTIVITIES": "workflows",
    "WORKFLOWS": "workflows",
    "BatchExportsMetricsInterceptor": "metrics",
}

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "BatchExportsMetricsInterceptor",
]


@cache
def _registration() -> TemporalRegistration:
    # Built on first access, like the names above, so that importing this facade stays light.
    from products.batch_exports.backend.temporal.metrics import (  # noqa: PLC0415 — keeps the destination SDKs off the import path
        BatchExportsMetricsInterceptor,
    )
    from products.batch_exports.backend.temporal.workflows import (  # noqa: PLC0415 — keeps the destination SDKs off the import path
        ACTIVITIES,
        WORKFLOWS,
    )

    return TemporalRegistration(
        queues=(
            QueueBinding(
                queue_setting="SYNC_BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
            ),
            QueueBinding(
                queue_setting="BATCH_EXPORTS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
            ),
        ),
        interceptors=(BatchExportsMetricsInterceptor,),
    )


def __getattr__(name: str) -> Any:
    if name == "TEMPORAL":
        return _registration()
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
