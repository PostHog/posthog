"""
Postgres destination wiring for batch_exports.

Re-exports the client and the transaction helper that the warehouse_sources Postgres and
Redshift writers reuse.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    Fields,
    PostgreSQLClient,
    PostgreSQLIntegrationNotFoundError,
    run_in_retryable_transaction,
)

__all__ = [
    "Fields",
    "PostgreSQLClient",
    "PostgreSQLIntegrationNotFoundError",
    "run_in_retryable_transaction",
]
