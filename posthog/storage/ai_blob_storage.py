import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from django.conf import settings

import structlog
from boto3 import client
from botocore.client import Config

from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

# S3 URL format: s3://bucket/key?range=start-end
S3_URL_PATTERN = re.compile(r"^s3://([^/]+)/(.+)$")


# Keys used in the blob reference object
AI_BLOB_URL_KEY = "$ai_blob_url"
AI_BLOB_RANGE_KEY = "$ai_blob_range"


# BlobReference is a dict with $ai_blob_url and $ai_blob_range keys
BlobReference = dict[str, str]


def _get_ai_s3_client():
    """Get a boto3 S3 client configured for AI blob storage."""
    return client(
        "s3",
        endpoint_url=settings.AI_S3_ENDPOINT,
        aws_access_key_id=settings.AI_S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AI_S3_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            connect_timeout=1,
            retries={"max_attempts": 1},
        ),
        region_name=settings.AI_S3_REGION,
    )


def parse_s3_url(s3_url: str) -> tuple[str, str, str] | None:
    """Parse an S3 URL into bucket, key, and range.

    Args:
        s3_url: URL in format s3://bucket/key?range=start-end

    Returns:
        Tuple of (bucket, key, range) or None if invalid
    """
    parsed = urlparse(s3_url)
    if parsed.scheme != "s3":
        return None

    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    query = parse_qs(parsed.query)
    range_param = query.get("range", [""])[0]

    if not bucket or not key:
        return None

    return bucket, key, range_param


def transform_s3_url_to_presigned(s3_url: str) -> BlobReference | None:
    """Transform an S3 URL to a presigned HTTPS URL with range info.

    Args:
        s3_url: URL in format s3://bucket/key?range=start-end

    Returns:
        BlobReference dict with presigned URL and range, or None if transformation fails
    """
    if not settings.AI_S3_BUCKET:
        logger.warning("ai_blob_storage.ai_s3_bucket_not_configured")
        return None

    parsed = parse_s3_url(s3_url)
    if not parsed:
        logger.warning("ai_blob_storage.invalid_s3_url", s3_url=s3_url)
        return None

    bucket, key, range_param = parsed

    # Validate bucket matches configured bucket
    if bucket != settings.AI_S3_BUCKET:
        logger.warning(
            "ai_blob_storage.bucket_mismatch",
            expected=settings.AI_S3_BUCKET,
            actual=bucket,
        )
        return None

    try:
        s3_client = _get_ai_s3_client()
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=settings.AI_BLOB_PRESIGNED_TTL_SECONDS,
            HttpMethod="GET",
        )

        return {
            AI_BLOB_URL_KEY: presigned_url,
            AI_BLOB_RANGE_KEY: range_param,
        }
    except Exception as e:
        logger.exception("ai_blob_storage.presign_failed", s3_url=s3_url, error=e)
        capture_exception(e)
        return None


def is_s3_blob_url(value: Any) -> bool:
    """Check if a value is an S3 blob URL."""
    return isinstance(value, str) and value.startswith("s3://")


def transform_blob_properties(properties: dict[str, Any]) -> None:
    """Transform S3 URLs in event properties to presigned URLs.

    This modifies the properties dict in-place, replacing S3 URLs with
    BlobReference objects containing presigned HTTPS URLs.

    Args:
        properties: Event properties dict to transform
    """
    if not settings.AI_S3_BUCKET:
        return

    for key, value in list(properties.items()):
        if is_s3_blob_url(value):
            blob_ref = transform_s3_url_to_presigned(value)
            if blob_ref:
                properties[key] = blob_ref
