"""
Model-class wiring for data_modeling.

Light re-exports of the data_modeling models' public surface — the ORM model classes,
their enums, and the in-module helpers cross-product object-consumers need (HogQL/query
builders that traverse the saved-query DAG, dispatch on ``isinstance``, or call model
methods). The models' heavy dependencies (HogQL, temporal) are deferred inside their
methods, so importing this adds nothing beyond the models Django loads at ``setup()``.

Note: ``NodeType`` here is ``models.node.NodeType`` (table/view/matview/endpoint). The
distinct resolver enum ``models.modeling.NodeType`` is exposed via ``facade.modeling``.
"""

from products.data_modeling.backend.graph import Graph
from products.data_modeling.backend.models.dag import (
    DAG,
    DEFAULT_DAG_NAME,
    RESERVED_DAG_NAMES,
    REVENUE_ANALYTICS_DAG_NAME,
)
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
from products.data_modeling.backend.models.datawarehouse_saved_query_column_annotation import (
    DataWarehouseSavedQueryColumnAnnotation,
)
from products.data_modeling.backend.models.datawarehouse_saved_query_draft import DataWarehouseSavedQueryDraft
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

__all__ = [
    "DAG",
    "DEFAULT_DAG_NAME",
    "RESERVED_DAG_NAMES",
    "REVENUE_ANALYTICS_DAG_NAME",
    "DataModelingJob",
    "DataModelingJobEngine",
    "DataModelingJobStatus",
    "DataWarehouseManagedViewSet",
    "DataWarehouseSavedQuery",
    "DataWarehouseSavedQueryColumnAnnotation",
    "DataWarehouseSavedQueryDraft",
    "Edge",
    "Graph",
    "Node",
    "NodeType",
    "aget_saved_query_by_id",
    "aget_table_by_saved_query_id",
    "asave_saved_query",
    "validate_saved_query_name",
]
