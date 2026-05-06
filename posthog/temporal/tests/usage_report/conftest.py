"""Shared fixtures for usage report tests.

`minio_workflow_ctx` yields a `WorkflowContext` whose `run_id` and
`date_str` are unique per test, then cleans up every S3 object written
under that prefix. Tests that use it hit real MinIO via
`posthog.storage.object_storage` instead of an in-memory fake — that
catches content-type / content-encoding / boto3 idiosyncrasies the
mocks can't.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from django.conf import settings

from boto3 import resource
from botocore.client import Config

from posthog.temporal.usage_report.storage import bucket, run_prefix
from posthog.temporal.usage_report.types import WorkflowContext


def _s3_resource():
    return resource(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_access_key_id=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name=settings.OBJECT_STORAGE_REGION,
    )


def _delete_prefix(prefix: str) -> None:
    s3 = _s3_resource()
    s3_bucket = s3.Bucket(bucket())
    s3_bucket.objects.filter(Prefix=prefix).delete()


@pytest.fixture
def minio_workflow_ctx() -> Iterator[WorkflowContext]:
    """A `WorkflowContext` whose run-prefix gets nuked from MinIO at teardown."""
    ctx = WorkflowContext(
        run_id=f"test-{uuid.uuid4().hex[:12]}",
        period_start=datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC),
        period_end=datetime(2026, 5, 4, 23, 59, 59, 999999, tzinfo=UTC),
        date_str=f"test-{uuid.uuid4().hex[:8]}",
    )
    try:
        yield ctx
    finally:
        _delete_prefix(run_prefix(ctx))
