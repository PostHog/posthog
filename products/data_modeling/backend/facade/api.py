"""
Facade for data_modeling.

Re-exports the saved-query / DAG operational services that sibling products and core
consume. Loaded lazily (PEP 562): the underlying services pull heavy dependencies
(HogQL, temporal) and sit alongside the warehouse import pipeline, so resolving each
name on first access keeps this module off the ``django.setup()`` path.
"""

_B = "products.data_modeling.backend."

_LAZY = {
    "HasDependentsError": "logic.saved_query_dag_sync",
    "UnsatisfiableFrequencyError": "logic.freshness",
    "UnsupportedFrequencyTargetError": "logic.freshness",
    "delete_node_from_dag": "logic.saved_query_dag_sync",
    "sync_saved_query_to_dag": "logic.saved_query_dag_sync",
    "update_node_type": "logic.saved_query_dag_sync",
    "is_saved_query_on_v2_schedule": "logic.node_materialization",
    "materialize_saved_query": "logic.node_materialization",
    "start_node_materialization": "logic.node_materialization",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(_B + module), name)
