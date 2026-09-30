"""
Google Cloud service account wiring for batch_exports.

Re-exports the helpers that let the warehouse_sources BigQuery source impersonate a customer's
service account through the same PostHog identity that BigQuery batch exports use.

These names live apart from ``facade/pipeline.py`` because the source resolves credentials on
web requests. ``facade/pipeline.py`` loads every destination's vendor SDK, and this module loads
only the BigQuery destination. It still pulls in the Google SDKs, so import it inside the
function that needs it, never at module level.
"""

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    MissingRequiredPermissionsError,
    ServiceAccountNotFoundError,
    ServiceAccountOwnershipError,
    get_our_google_cloud_credentials,
    verify_impersonated_service_account_ownership,
)

__all__ = [
    "MissingRequiredPermissionsError",
    "ServiceAccountNotFoundError",
    "ServiceAccountOwnershipError",
    "get_our_google_cloud_credentials",
    "verify_impersonated_service_account_ownership",
]
