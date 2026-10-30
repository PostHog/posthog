"""Destination capability tables that must stay import-light.

The destination modules import their vendor SDKs at module scope, so anything that only
needs these tables should import them from here instead of the destination module. The
compression tables live in ``facade/enums.py``, because the API serializers read them too.
"""

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
