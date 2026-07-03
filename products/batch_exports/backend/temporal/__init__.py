"""Batch export Temporal workflows and activities.

The worker-facing aggregator (``WORKFLOWS`` / ``ACTIVITIES`` and every workflow class)
lives in ``workflows.py`` and is resolved lazily via PEP 562 ``__getattr__``. Eager
imports here would make *any* ``...temporal.<submodule>`` import pay for every
destination's vendor SDK (databricks, snowflake, bigquery, …) — which put ~1.6s on the
Django startup path when the API module imported a single constants table from one
destination. Only the Temporal worker needs the full set, and it still gets it through
``from products.batch_exports.backend.temporal import WORKFLOWS, ACTIVITIES``.
"""

import time
import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.batch_exports.backend.temporal.workflows import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]

_WORKFLOWS_MODULE = "products.batch_exports.backend.temporal.workflows"

# ``ACTIVITIES``/``WORKFLOWS`` are bound at the very *end* of ``workflows.py``, after a long
# chain of destination-submodule imports. If that module is still executing further up the
# stack when we resolve here (a concurrent import from another thread/greenlet finishing the
# module), ``import_module`` hands back the half-initialized module and ``getattr`` misses —
# surfacing as a confusing ``ImportError: cannot import name 'ACTIVITIES'``. Bound retries let
# the in-flight import finish before we give up with a clear, actionable message.
_PARTIAL_MODULE_RETRIES = 50
_PARTIAL_MODULE_RETRY_SLEEP = 0.05


def __getattr__(name: str) -> Any:
    # Only the worker-facing aggregator names resolve through here; everything else raises
    # AttributeError so ``from <this package> import <submodule>`` falls back to a regular
    # submodule import. A catch-all would eagerly load the aggregator on that probe — and
    # deadlock on a circular import, since aggregated modules import siblings through the
    # package root (e.g. record_batch_model imports ``sql``).
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    for _ in range(_PARTIAL_MODULE_RETRIES):
        workflows = importlib.import_module(_WORKFLOWS_MODULE)
        try:
            return getattr(workflows, name)
        except AttributeError:
            # ``workflows`` is in sys.modules but the aggregator names are not bound yet — the
            # module is mid-initialization elsewhere. Yield so that import can complete, then
            # re-resolve against the now-cached module.
            time.sleep(_PARTIAL_MODULE_RETRY_SLEEP)

    raise ImportError(
        f"cannot resolve {name!r} from {_WORKFLOWS_MODULE!r}: the module is still initializing "
        f"(its aggregator names are bound only after every destination submodule imports). This "
        f"indicates a re-entrant import of the batch-exports Temporal package during worker "
        f"startup; retry the import or restart the worker.",
        name=name,
        path=_WORKFLOWS_MODULE,
    )


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
