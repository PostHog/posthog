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

FILE_FORMAT_EXTENSIONS: dict[str, str] = {
    "Parquet": "parquet",
    "JSONLines": "jsonl",
}

COMPRESSION_EXTENSIONS: dict[str, str] = {
    "gzip": "gz",
    "snappy": "sz",
    "brotli": "br",
    "zstd": "zst",
    "lz4": "lz4",
}
