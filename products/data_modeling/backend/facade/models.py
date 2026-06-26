"""
Model-class wiring for data_modeling.

Light re-exports of the data_modeling models' public surface — the ORM model classes,
their enums, and the module-level helpers/resolvers cross-product object-consumers need
(HogQL/query builders that traverse the saved-query DAG, dispatch on ``isinstance``, or
call model methods). The models' heavy dependencies (HogQL, temporal) are deferred
inside their methods, so importing this adds nothing beyond the models Django already
loads at ``django.setup()``.
"""

from products.data_modeling.backend.graph import Graph
from products.data_modeling.backend.models.dag import DAG, DEFAULT_DAG_NAME
from products.data_modeling.backend.models.data_modeling_job import (
    DataModelingJob,
    DataModelingJobEngine,
    DataModelingJobStatus,
)
from products.data_modeling.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_modeling.backend.models.datawarehouse_saved_query import (
    DataWarehouseSavedQuery,
    aget_saved_query_by_id,
    aget_table_by_saved_query_id,
    asave_saved_query,
    validate_saved_query_name,
)
from products.data_modeling.backend.models.datawarehouse_saved_query_draft import DataWarehouseSavedQueryDraft
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.modeling import (
    DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
    BoundedResolver,
    DataWarehouseModelPath,
    ResolutionCycleError,
    ResolutionDepthExceededError,
    ResolutionTimeoutError,
    bounded_resolver_factory_for_view,
    get_parents_from_model_query,
)
from products.data_modeling.backend.models.node import Node, NodeType

__all__ = [
    "DAG",
    "DEFAULT_DAG_NAME",
    "DEFAULT_RESOLUTION_DEADLINE_SECONDS",
    "DEFAULT_RESOLUTION_MAX_VIEW_DEPTH",
    "BoundedResolver",
    "DataModelingJob",
    "DataModelingJobEngine",
    "DataModelingJobStatus",
    "DataWarehouseManagedViewSet",
    "DataWarehouseModelPath",
    "DataWarehouseSavedQuery",
    "DataWarehouseSavedQueryDraft",
    "Edge",
    "Graph",
    "Node",
    "NodeType",
    "ResolutionCycleError",
    "ResolutionDepthExceededError",
    "ResolutionTimeoutError",
    "aget_saved_query_by_id",
    "aget_table_by_saved_query_id",
    "asave_saved_query",
    "bounded_resolver_factory_for_view",
    "get_parents_from_model_query",
    "validate_saved_query_name",
]
