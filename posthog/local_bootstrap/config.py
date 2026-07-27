from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Mirrors the file formats and compression methods supported by the PostHog S3 batch export
# feature (see products/batch_exports/.../destinations/constants.py). Kept as a local copy so the
# bootstrapper has no import-time dependency on the Temporal batch-export package.
SUPPORTED_FILE_FORMATS = ("Parquet", "JSONLines")

S3_SUPPORTED_COMPRESSIONS: dict[str, tuple[str, ...]] = {
    "Parquet": ("zstd", "lz4", "snappy", "gzip", "brotli"),
    "JSONLines": ("gzip", "brotli"),
}

# Extension a file of a given format/compression carries in the export bucket.
FILE_FORMAT_EXTENSIONS = {"Parquet": "parquet", "JSONLines": "jsonl"}
COMPRESSION_EXTENSIONS = {"gzip": "gz", "snappy": "sz", "brotli": "br", "zstd": "zst", "lz4": "lz4"}

Table = Literal["events", "persons"]


class BootstrapConfigError(Exception):
    """Raised when the import configuration is invalid (bad format, missing bucket, etc.)."""


@dataclass
class S3Location:
    """Where a dump lives and how to authenticate against it."""

    bucket: str
    prefix: str = ""
    access_key_id: str | None = None
    secret_access_key: str | None = None
    region: str | None = None
    # Custom S3-compatible endpoint (MinIO, SeaweedFS, Cloudflare R2, ...). None uses AWS.
    endpoint_url: str | None = None


@dataclass
class TableImportConfig:
    """Everything needed to import one table from one location."""

    table: Table
    location: S3Location
    file_format: str = "Parquet"
    compression: str | None = "zstd"

    def validate(self) -> None:
        if self.file_format not in SUPPORTED_FILE_FORMATS:
            raise BootstrapConfigError(
                f"Unsupported file format {self.file_format!r}. Supported: {', '.join(SUPPORTED_FILE_FORMATS)}"
            )
        if self.compression is not None and self.compression not in S3_SUPPORTED_COMPRESSIONS[self.file_format]:
            allowed = ", ".join(S3_SUPPORTED_COMPRESSIONS[self.file_format])
            raise BootstrapConfigError(
                f"Compression {self.compression!r} is not supported for {self.file_format} "
                f"(supported: {allowed}, or none)"
            )
        if not self.location.bucket:
            raise BootstrapConfigError(f"A bucket is required for the {self.table} table")


@dataclass
class BootstrapConfig:
    """Full configuration for a bootstrap run."""

    project_name: str
    email: str = ""
    password: str = ""
    tables: list[TableImportConfig] = field(default_factory=list)
    batch_size: int = 10_000

    def validate(self, require_identity: bool = True) -> None:
        if require_identity and not self.project_name:
            raise BootstrapConfigError("A project name is required")
        if require_identity and not self.email:
            raise BootstrapConfigError("An email is required")
        if not self.tables:
            raise BootstrapConfigError("At least one of the events or persons tables must be configured")
        for table in self.tables:
            table.validate()


@dataclass
class DiscoveredFile:
    """A single object found in the export bucket that will be imported."""

    key: str
    size_bytes: int


@dataclass
class TablePlan:
    """The set of files discovered for a table, ready to be shown to the user before import."""

    config: TableImportConfig
    files: list[DiscoveredFile]

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_size_bytes(self) -> int:
        return sum(f.size_bytes for f in self.files)


@dataclass
class TableResult:
    """The outcome of importing one table."""

    table: Table
    rows_imported: int
    distinct_ids_imported: int = 0
