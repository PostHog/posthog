"""Destination capability tables that must stay import-light.

The destination modules import their vendor SDKs at module scope, so anything that only
needs these tables — like the batch exports API serializers validating file format and
compression combinations — should import them from here instead of the destination module.
"""

# The only destination URLs an HTTP batch export can send to. Both the API serializer and the
# Temporal activity reject any other URL, so anything that creates an HTTP export must use one of these.
ALLOWED_HTTP_BATCH_EXPORT_URLS: tuple[str, ...] = (
    "https://us.i.posthog.com/batch/",
    "https://eu.i.posthog.com/batch/",
)

S3_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

AZURE_BLOB_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}
