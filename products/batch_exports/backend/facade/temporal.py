"""
Temporal registration wiring for batch_exports.

Re-exports what core registers with Temporal: the worker bootstrap commands
(``start_temporal_worker``, ``start_temporal_workflow``, ``execute_temporal_workflow``)
take ``WORKFLOWS`` and ``ACTIVITIES``, ``posthog/temporal/common/worker.py`` takes the
metrics interceptor, and the shared Temporal test conftest and payload-codec test take
the no-op workflow and its activity.

Names resolve lazily (PEP 562), mirroring ``backend/temporal/__init__.py``. Eager imports
here would put every destination's vendor SDK (databricks, snowflake, bigquery, ...) on
the import path of anything that touches this facade, which the startup import budget
forbids — see ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.batch_exports.backend.temporal.metrics import BatchExportsMetricsInterceptor
    from products.batch_exports.backend.temporal.noop import NoOpWorkflow, noop_activity
    from products.batch_exports.backend.temporal.workflows import ACTIVITIES, WORKFLOWS

_B = "products.batch_exports.backend.temporal."

_LAZY = {
    "ACTIVITIES": "workflows",
    "WORKFLOWS": "workflows",
    "BatchExportsMetricsInterceptor": "metrics",
    "NoOpWorkflow": "noop",
    "noop_activity": "noop",
}

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "BatchExportsMetricsInterceptor",
    "NoOpWorkflow",
    "noop_activity",
]


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
