"""
Redshift destination wiring for batch_exports.

Re-exports the client and the connection resolver that the warehouse_sources Redshift
writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.redshift_batch_export import (
    RedshiftClient,
    StringLimitExceededError,
    resolve_redshift_client_inputs,
)

__all__ = [
    "RedshiftClient",
    "StringLimitExceededError",
    "resolve_redshift_client_inputs",
]
