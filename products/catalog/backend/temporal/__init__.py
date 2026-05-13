"""Temporal workflows + activities for the catalog product.

The temporal-django worker discovers these via explicit registration in
`posthog/management/commands/start_temporal_worker.py`. Imports here are kept
flat so the registration site can do `from products.catalog.backend.temporal
import WORKFLOWS, ACTIVITIES` without reaching into submodules.
"""

from products.catalog.backend.temporal.activities import (
    complete_traversal_run,
    create_traversal_run,
    enumerate_warehouse_tables,
    fail_traversal_run,
    upsert_warehouse_batch,
)
from products.catalog.backend.temporal.workflow import CatalogTraversalWorkflow

WORKFLOWS = [CatalogTraversalWorkflow]

ACTIVITIES = [
    create_traversal_run,
    complete_traversal_run,
    fail_traversal_run,
    enumerate_warehouse_tables,
    upsert_warehouse_batch,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "CatalogTraversalWorkflow",
    "complete_traversal_run",
    "create_traversal_run",
    "enumerate_warehouse_tables",
    "fail_traversal_run",
    "upsert_warehouse_batch",
]
