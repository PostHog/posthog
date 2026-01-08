import json
import uuid
import dataclasses
from typing import Any

from django.conf import settings

import pyarrow as pa
import pyarrow.ipc as ipc

from products.data_warehouse.backend.s3 import get_s3_client


@dataclasses.dataclass
class BatchInfo:
    """Information about a single batch/parquet file."""

    path: str
    row_count: int


@dataclasses.dataclass
class ETManifest:
    """Metadata contract between ET and L workflows."""

    temp_s3_prefix: str
    parquet_files: list[str]
    schema_path: str
    hogql_schema: dict[str, str]
    table_name: str
    primary_keys: list[str] | None
    partition_count: int | None
    partition_keys: list[str] | None
    partition_mode: str | None  # "md5", "numerical", "datetime"
    sync_type: str  # "full_refresh", "incremental", "append"
    incremental_field: str | None
    incremental_field_last_value: Any
    incremental_field_earliest_value: Any
    team_id: int
    source_id: str
    schema_id: str
    job_id: str
    run_id: str
    total_rows: int
    batch_info: list[dict] | None = None  # List of {path, row_count}

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ETManifest":
        return cls(**data)

    def get_manifest_path(self) -> str:
        return f"{self.temp_s3_prefix}/manifest.json"

    def get_batch_row_count(self, batch_number: int) -> int | None:
        """Get row count for a specific batch by its index."""
        if self.batch_info and batch_number < len(self.batch_info):
            return self.batch_info[batch_number].get("row_count")
        return None

    def save_to_s3(self) -> str:
        """Save manifest to S3, return manifest path."""
        s3_client = get_s3_client()
        manifest_path = self.get_manifest_path()

        s3_client.write_text(
            f"{settings.BUCKET_URL}/{manifest_path}",
            json.dumps(self.to_dict()),
        )
        return manifest_path

    @classmethod
    def load_from_s3(cls, manifest_path: str) -> "ETManifest":
        """Load manifest from S3."""
        s3_client = get_s3_client()

        data = json.loads(s3_client.read_text(f"{settings.BUCKET_URL}/{manifest_path}"))
        return cls.from_dict(data)


def save_schema_to_s3(schema: pa.Schema, temp_s3_prefix: str) -> str:
    """Save PyArrow schema to S3 in IPC format."""
    s3_client = get_s3_client()
    schema_path = f"{temp_s3_prefix}/schema.arrow"

    sink = pa.BufferOutputStream()
    writer = ipc.new_stream(sink, schema)
    writer.close()
    schema_bytes = sink.getvalue().to_pybytes()

    with s3_client.open(f"{settings.BUCKET_URL}/{schema_path}", "wb") as f:
        f.write(schema_bytes)

    return schema_path


def load_schema_from_s3(schema_path: str) -> pa.Schema:
    """Load PyArrow schema from S3."""
    s3_client = get_s3_client()

    with s3_client.open(f"{settings.BUCKET_URL}/{schema_path}", "rb") as f:
        schema_bytes = f.read()

    reader = ipc.open_stream(pa.BufferReader(schema_bytes))
    return reader.schema


def generate_temp_s3_prefix(team_id: int, job_id: str) -> str:
    """Generate a unique temp S3 prefix for this job run."""
    run_id = str(uuid.uuid4())
    return f"temp/{team_id}/{job_id}/{run_id}"
