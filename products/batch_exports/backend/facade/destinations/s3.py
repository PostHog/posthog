"""
S3 destination wiring for batch_exports.

Re-exports the client, the upload consumer and the credential helpers that the
warehouse_sources S3 writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

import datetime as dt

from products.batch_exports.backend.facade.enums import S3_SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.service import BatchExportModel
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    ConcurrentS3Consumer,
    ExternalRoleArnNotConfiguredError,
    IntermittentUploadPartTimeoutError,
    InvalidCredentialsError,
    PolicyStatement,
    S3IntegrationNotFoundError,
    _get_s3_integration as get_s3_integration,
    get_credentials_using_user_aws_role,
    s3_client,
)
from products.batch_exports.backend.temporal.destinations.utils import get_key_prefix

__all__ = [
    "ConcurrentS3Consumer",
    "ExternalRoleArnNotConfiguredError",
    "IntermittentUploadPartTimeoutError",
    "InvalidCredentialsError",
    "PolicyStatement",
    "S3IntegrationNotFoundError",
    "S3_SUPPORTED_COMPRESSIONS",
    "get_credentials_using_user_aws_role",
    "get_s3_integration",
    "s3_client",
    "render_key_prefix",
]


def render_key_prefix(prefix: str, *, at: dt.datetime, table: str) -> str:
    """Fill a key prefix the way an S3 batch export does, with `at` as the export time and `table` as `{table}`."""
    return get_key_prefix(
        prefix,
        data_interval_start=None,
        data_interval_end=at.isoformat(),
        batch_export_model=BatchExportModel(name=table, schema=None),
    )
