"""The one place that knows how the rasterizer's `s3://` output maps onto an asset's `content_location`."""

from django.conf import settings


def content_location_from_s3_uri(s3_uri: str) -> str:
    """Strip the bucket prefix the Node uploader returns, leaving the key an ExportedAsset stores."""
    prefix = f"s3://{settings.OBJECT_STORAGE_BUCKET}/"
    if not s3_uri.startswith(prefix):
        raise ValueError(f"Unexpected s3_uri prefix: {s3_uri} (expected {prefix}...)")
    return s3_uri[len(prefix) :]
