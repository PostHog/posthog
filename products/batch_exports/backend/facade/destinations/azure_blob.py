"""
Azure Blob destination wiring for batch_exports.

Re-exports the integration lookup, error helpers and compression list that the
warehouse_sources Azure Blob writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    MalformedConnectionStringError,
    _get_azure_blob_integration as get_azure_blob_integration,
    _is_authorization_failure_response_error as is_authorization_failure_response_error,
)
from products.batch_exports.backend.temporal.destinations.constants import AZURE_BLOB_SUPPORTED_COMPRESSIONS

__all__ = [
    "AZURE_BLOB_SUPPORTED_COMPRESSIONS",
    "MalformedConnectionStringError",
    "get_azure_blob_integration",
    "is_authorization_failure_response_error",
]
