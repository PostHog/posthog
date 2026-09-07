"""Destination capability tables that must stay import-light.

The destination modules import their vendor SDKs at module scope, so anything that only
needs these tables — like the batch exports API serializers validating file format and
compression combinations — should import them from here instead of the destination module.
"""

S3_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

AZURE_BLOB_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

# The only destinations an HTTP batch export may send to. Any other URL is an SSRF risk.
HTTP_ALLOWED_DESTINATION_URLS: frozenset[str] = frozenset(
    {
        "https://us.i.posthog.com/batch/",
        "https://eu.i.posthog.com/batch/",
    }
)
