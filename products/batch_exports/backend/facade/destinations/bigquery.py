"""
BigQuery destination wiring for batch_exports.

Re-exports the BigQuery client that the warehouse_sources BigQuery writer reuses, and the
service account helpers that let the BigQuery import source impersonate a customer's service
account through the same PostHog identity that BigQuery batch exports use.

The import source resolves credentials on web requests, so it imports this module inside the
function that needs it.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    MissingRequiredPermissionsError,
    ServiceAccountNotFoundError,
    ServiceAccountOwnershipError,
    get_our_google_cloud_credentials,
    verify_impersonated_service_account_ownership,
)

__all__ = [
    "BigQueryClient",
    "MissingRequiredPermissionsError",
    "ServiceAccountNotFoundError",
    "ServiceAccountOwnershipError",
    "get_our_google_cloud_credentials",
    "verify_impersonated_service_account_ownership",
]
