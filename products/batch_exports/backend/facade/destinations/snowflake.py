"""
Snowflake destination wiring for batch_exports.

Re-exports the client, the table types and the credential helpers that the warehouse_sources
Snowflake writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    NamedBytesIO,
    SnowflakeClient,
    SnowflakeField,
    SnowflakeTable,
    SnowflakeType,
    _get_snowflake_integration as get_snowflake_integration,
    load_private_key,
)

__all__ = [
    "NamedBytesIO",
    "SnowflakeClient",
    "SnowflakeField",
    "SnowflakeTable",
    "SnowflakeType",
    "get_snowflake_integration",
    "load_private_key",
]
