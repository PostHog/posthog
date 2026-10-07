"""
S3 destination wiring for batch_exports.

Re-exports the client, the upload consumer and the credential helpers that the
warehouse_sources S3 writer reuses.

Importing this module loads the destination's vendor SDK, so keep it off the
``django.setup()`` path. See ``posthog/test/repo_invariants/test_startup_import_budget.py``.
"""

from products.batch_exports.backend.temporal.destinations.constants import S3_SUPPORTED_COMPRESSIONS
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    ConcurrentS3Consumer,
    IntermittentUploadPartTimeoutError,
    PolicyStatement,
    _get_s3_integration as get_s3_integration,
    get_credentials_using_user_aws_role,
    s3_client,
)

__all__ = [
    "ConcurrentS3Consumer",
    "IntermittentUploadPartTimeoutError",
    "PolicyStatement",
    "S3_SUPPORTED_COMPRESSIONS",
    "get_credentials_using_user_aws_role",
    "get_s3_integration",
    "s3_client",
]
