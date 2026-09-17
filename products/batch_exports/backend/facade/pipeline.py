"""
Export-pipeline wiring for batch_exports.

Re-exports the destination clients, stream transformers and credential helpers that the
warehouse_sources Temporal writers reuse, so a data-import writer and a batch export talk
to Snowflake, BigQuery, Databricks, Postgres, Redshift, S3 and Azure Blob the same way.

Every name here comes from ``backend/temporal/``, so importing this module pulls each
destination's vendor SDK. Only Temporal activity code may import it. Never import it from
``facade/api.py``, or from anything else on the ``django.setup()`` path — see
``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.azure_blob_batch_export import (
    MalformedConnectionStringError,
    _get_azure_blob_integration as get_azure_blob_integration,
    _is_authorization_failure_response_error as is_authorization_failure_response_error,
)
from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import (
    BigQueryClient,
    verify_impersonated_service_account_ownership,
)
from products.batch_exports.backend.temporal.destinations.constants import (
    AZURE_BLOB_SUPPORTED_COMPRESSIONS,
    S3_SUPPORTED_COMPRESSIONS,
)
from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    FIVE_MINUTES,
    ONE_HOUR,
    ONE_MINUTE,
    DatabricksClient,
    DatabricksField,
    DatabricksIntegrationNotFoundError,
    handle_common_errors,
)
from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    Fields,
    PostgreSQLClient,
    PostgreSQLIntegrationNotFoundError,
    run_in_retryable_transaction,
)
from products.batch_exports.backend.temporal.destinations.redshift_batch_export import RedshiftClient
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    ConcurrentS3Consumer,
    IntermittentUploadPartTimeoutError,
    PolicyStatement,
    _get_s3_integration as get_s3_integration,
    get_credentials_using_user_aws_role,
    s3_client,
)
from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    NamedBytesIO,
    SnowflakeClient,
    SnowflakeField,
    SnowflakeTable,
    SnowflakeType,
    _get_snowflake_integration as get_snowflake_integration,
    load_private_key,
)
from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer, ParquetStreamTransformer

from .contracts import AWSCredentials

__all__ = [
    "AWSCredentials",
    "AZURE_BLOB_SUPPORTED_COMPRESSIONS",
    "BigQueryClient",
    "CSVStreamTransformer",
    "ConcurrentS3Consumer",
    "DatabricksClient",
    "DatabricksField",
    "DatabricksIntegrationNotFoundError",
    "FIVE_MINUTES",
    "Fields",
    "IntermittentUploadPartTimeoutError",
    "MalformedConnectionStringError",
    "NamedBytesIO",
    "ONE_HOUR",
    "ONE_MINUTE",
    "ParquetStreamTransformer",
    "PolicyStatement",
    "PostgreSQLClient",
    "PostgreSQLIntegrationNotFoundError",
    "RedshiftClient",
    "S3_SUPPORTED_COMPRESSIONS",
    "SnowflakeClient",
    "SnowflakeField",
    "SnowflakeTable",
    "SnowflakeType",
    "get_azure_blob_integration",
    "get_credentials_using_user_aws_role",
    "get_s3_integration",
    "get_snowflake_integration",
    "handle_common_errors",
    "is_authorization_failure_response_error",
    "load_private_key",
    "run_in_retryable_transaction",
    "s3_client",
    "verify_impersonated_service_account_ownership",
]
