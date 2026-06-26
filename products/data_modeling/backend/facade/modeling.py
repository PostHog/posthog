"""
Model-path / resolver wiring for data_modeling.

Re-exports the saved-query DAG resolver surface from ``models.modeling`` — the
``DataWarehouseModelPath`` model, the bounded resolver, and its ``NodeType`` (note: a
distinct enum from ``models.node.NodeType``, which ``facade.models`` exposes). Light at
module level (modeling's heavy deps are deferred inside its methods).
"""

from products.data_modeling.backend.models.modeling import (
    DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
    BoundedResolver,
    DataWarehouseModelPath,
    NodeType,
    ResolutionCycleError,
    ResolutionDepthExceededError,
    ResolutionTimeoutError,
    bounded_resolver_factory_for_view,
    get_parents_from_model_query,
)

__all__ = [
    "DEFAULT_RESOLUTION_DEADLINE_SECONDS",
    "DEFAULT_RESOLUTION_MAX_VIEW_DEPTH",
    "BoundedResolver",
    "DataWarehouseModelPath",
    "NodeType",
    "ResolutionCycleError",
    "ResolutionDepthExceededError",
    "ResolutionTimeoutError",
    "bounded_resolver_factory_for_view",
    "get_parents_from_model_query",
]
