from __future__ import annotations

import os
import gzip
import json
import tempfile
import contextlib
from collections.abc import Callable, Iterator
from typing import IO, Any

import boto3
import pyarrow.parquet as pq

from posthog.local_bootstrap.config import (
    COMPRESSION_EXTENSIONS,
    FILE_FORMAT_EXTENSIONS,
    BootstrapConfigError,
    DiscoveredFile,
    S3Location,
    TableImportConfig,
)


# boto3.client("s3") is left untyped on purpose: mypy and ty resolve it to different stub packages
# (mypy_boto3_s3 vs types_boto3_s3), so a concrete S3Client annotation can't satisfy both checkers.
def build_s3_client(location: S3Location):
    """Build a boto3 S3 client for a location. Credentials fall back to the ambient AWS config
    (env vars, instance profile) when not supplied, so the same code works against AWS and
    S3-compatible stores like MinIO/SeaweedFS via ``endpoint_url``."""
    return boto3.client(
        "s3",
        aws_access_key_id=location.access_key_id or None,
        aws_secret_access_key=location.secret_access_key or None,
        region_name=location.region or None,
        endpoint_url=location.endpoint_url or None,
    )


def _matches_format(key: str, file_format: str) -> bool:
    """A key belongs to a format if it carries that format's extension, optionally followed by a
    compression extension (e.g. ``.parquet`` or ``.parquet.zst``). Manifest files are excluded."""
    if key.endswith("/") or key.endswith("_manifest.json"):
        return False
    format_ext = FILE_FORMAT_EXTENSIONS[file_format]
    suffixes = {f".{format_ext}"} | {f".{format_ext}.{c}" for c in COMPRESSION_EXTENSIONS.values()}
    return any(key.endswith(suffix) for suffix in suffixes)


def list_files(config: TableImportConfig) -> list[DiscoveredFile]:
    """List every object under the configured prefix that matches the table's file format."""
    client = build_s3_client(config.location)
    paginator = client.get_paginator("list_objects_v2")
    files: list[DiscoveredFile] = []
    for page in paginator.paginate(Bucket=config.location.bucket, Prefix=config.location.prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if _matches_format(key, config.file_format):
                files.append(DiscoveredFile(key=key, size_bytes=obj.get("Size", 0)))
    files.sort(key=lambda f: f.key)
    return files


@contextlib.contextmanager
def _download_to_temp(client, bucket: str, key: str) -> Iterator[str]:
    """Download an object to a temp file and yield its path, removing it afterwards. Reading from a
    real file lets pyarrow stream row groups instead of buffering the whole object in memory."""
    suffix = os.path.splitext(key)[1] or ".tmp"
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ph-bootstrap-")
    os.close(fd)
    try:
        client.download_file(bucket, key, path)
        yield path
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(path)


def _iter_parquet_rows(path: str, batch_size: int) -> Iterator[dict[str, Any]]:
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=batch_size):
        yield from batch.to_pylist()


def _open_maybe_compressed(path: str, key: str, compression: str | None) -> IO[str]:
    """Open a (possibly compression-wrapped) text file for JSONLines reading. Parquet handles its
    own codec internally; this outer decompression only applies to JSONLines dumps."""
    if key.endswith(".gz") or compression == "gzip":
        return gzip.open(path, "rt", encoding="utf-8")
    if key.endswith(".br") or compression == "brotli":
        import brotli  # noqa: PLC0415 — optional dep, only needed for brotli-compressed JSONLines

        with open(path, "rb") as compressed:
            data = brotli.decompress(compressed.read()).decode("utf-8")
        import io  # noqa: PLC0415

        return io.StringIO(data)
    return open(path, encoding="utf-8")


def _iter_jsonl_rows(path: str, key: str, compression: str | None) -> Iterator[dict[str, Any]]:
    with _open_maybe_compressed(path, key, compression) as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_table_rows(
    config: TableImportConfig,
    files: list[DiscoveredFile],
    batch_size: int,
    on_file_start: Callable[[DiscoveredFile, int], None] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every row across all of a table's files as plain dicts, downloading one file at a
    time. ``on_file_start(file, index)`` is called before each file so callers can report progress."""
    client = build_s3_client(config.location)
    for index, discovered in enumerate(files):
        if on_file_start is not None:
            on_file_start(discovered, index)
        with _download_to_temp(client, config.location.bucket, discovered.key) as path:
            if config.file_format == "Parquet":
                yield from _iter_parquet_rows(path, batch_size)
            elif config.file_format == "JSONLines":
                yield from _iter_jsonl_rows(path, discovered.key, config.compression)
            else:  # pragma: no cover - guarded by config.validate()
                raise BootstrapConfigError(f"Cannot read file format {config.file_format!r}")
