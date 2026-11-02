"""
Snowflake destination wiring for batch_exports.

Re-exports the client, the table types and the credential helpers that the warehouse_sources
Snowflake writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    InvalidPrivateKeyError,
    NamedBytesIO,
    SnowflakeAuthenticationError,
    SnowflakeClient,
    SnowflakeConnectionError,
    SnowflakeField,
    SnowflakeFileNotLoadedError,
    SnowflakeIncompatibleSchemaError,
    SnowflakeInsufficientPrivilegesError,
    SnowflakeIntegrationNotFoundError,
    SnowflakeQueryClientTimeoutError,
    SnowflakeQueryServerTimeoutError,
    SnowflakeRetryableConnectionError,
    SnowflakeTable,
    SnowflakeType,
    SnowflakeWarehouseSuspendedError,
    SnowflakeWarehouseUsageError,
    _get_snowflake_integration as get_snowflake_integration,
    load_private_key,
)

__all__ = [
    "InvalidPrivateKeyError",
    "NamedBytesIO",
    "SnowflakeAuthenticationError",
    "SnowflakeClient",
    "SnowflakeConnectionError",
    "SnowflakeField",
    "SnowflakeFileNotLoadedError",
    "SnowflakeIncompatibleSchemaError",
    "SnowflakeInsufficientPrivilegesError",
    "SnowflakeIntegrationNotFoundError",
    "SnowflakeQueryClientTimeoutError",
    "SnowflakeQueryServerTimeoutError",
    "SnowflakeRetryableConnectionError",
    "SnowflakeTable",
    "SnowflakeType",
    "SnowflakeWarehouseSuspendedError",
    "SnowflakeWarehouseUsageError",
    "get_snowflake_integration",
    "load_private_key",
]
