"""Batch export Temporal workflows and activities.

The worker-facing aggregator (``WORKFLOWS`` / ``ACTIVITIES`` and every workflow class)
lives in ``workflows.py`` and is resolved lazily via PEP 562 ``__getattr__``. Eager
imports here would make *any* ``...temporal.<submodule>`` import pay for every
destination's vendor SDK (databricks, snowflake, bigquery, …) — which put ~1.6s on the
Django startup path when the API module imported a single constants table from one
destination. Only the Temporal worker needs the full set, and it still gets it through
``from products.batch_exports.backend.temporal import WORKFLOWS, ACTIVITIES``.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.batch_exports.backend.temporal.workflows import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]


def __getattr__(name: str) -> Any:
    # Only the worker-facing aggregator names resolve through here; everything else raises
    # AttributeError so ``from <this package> import <submodule>`` falls back to a regular
    # submodule import. A catch-all would eagerly load the aggregator on that probe — and
    # deadlock on a circular import, since aggregated modules import siblings through the
    # package root (e.g. record_batch_model imports ``sql``).
    if name in __all__:
        workflows = importlib.import_module("products.batch_exports.backend.temporal.workflows")
        return getattr(workflows, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
