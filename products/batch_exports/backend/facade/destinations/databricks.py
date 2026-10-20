"""
Databricks destination wiring for batch_exports.

Re-exports the client, the field type and the error handling that the warehouse_sources
Databricks writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    FIVE_MINUTES,
    ONE_HOUR,
    ONE_MINUTE,
    DatabricksCatalogNotFoundError,
    DatabricksClient,
    DatabricksConnectionError,
    DatabricksField,
    DatabricksIncompatibleSchemaError,
    DatabricksInsufficientPermissionsError,
    DatabricksIntegrationNotFoundError,
    DatabricksOperationTimeoutError,
    DatabricksSchemaNotFoundError,
    DatabricksWarehouseStoppedError,
    handle_common_errors,
)

__all__ = [
    "DatabricksCatalogNotFoundError",
    "DatabricksClient",
    "DatabricksConnectionError",
    "DatabricksField",
    "DatabricksIncompatibleSchemaError",
    "DatabricksInsufficientPermissionsError",
    "DatabricksIntegrationNotFoundError",
    "DatabricksOperationTimeoutError",
    "DatabricksSchemaNotFoundError",
    "DatabricksWarehouseStoppedError",
    "FIVE_MINUTES",
    "ONE_HOUR",
    "ONE_MINUTE",
    "handle_common_errors",
]
