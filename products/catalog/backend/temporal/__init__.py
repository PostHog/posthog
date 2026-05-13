"""Temporal workflows + activities for the catalog product.

The temporal-django worker discovers these via explicit registration in
`posthog/management/commands/start_temporal_worker.py`. Imports here are kept
flat so the registration site can do `from products.catalog.backend.temporal
import WORKFLOWS, ACTIVITIES` without reaching into submodules.
"""

from products.catalog.backend.temporal.activities import (
    complete_traversal_run,
    create_traversal_run,
    enumerate_posthog_tables,
    enumerate_saved_queries,
    enumerate_system_tables,
    enumerate_warehouse_tables,
    fail_traversal_run,
    propose_native_fks,
    propose_saved_query_lineage,
    propose_warehouse_joins,
    upsert_node_batch,
)
from products.catalog.backend.temporal.workflow import CatalogTraversalWorkflow

WORKFLOWS = [CatalogTraversalWorkflow]

ACTIVITIES = [
    create_traversal_run,
    complete_traversal_run,
    fail_traversal_run,
    enumerate_warehouse_tables,
    enumerate_saved_queries,
    enumerate_system_tables,
    enumerate_posthog_tables,
    upsert_node_batch,
    propose_native_fks,
    propose_warehouse_joins,
    propose_saved_query_lineage,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "CatalogTraversalWorkflow",
    "complete_traversal_run",
    "create_traversal_run",
    "enumerate_posthog_tables",
    "enumerate_saved_queries",
    "enumerate_system_tables",
    "enumerate_warehouse_tables",
    "fail_traversal_run",
    "propose_native_fks",
    "propose_saved_query_lineage",
    "propose_warehouse_joins",
    "upsert_node_batch",
]
