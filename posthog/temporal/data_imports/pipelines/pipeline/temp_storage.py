from typing import Any

from django.conf import settings

import pyarrow as pa
import pyarrow.parquet as pq

from posthog.temporal.data_imports.pipelines.pipeline.et_manifest import (
    ETManifest,
    generate_temp_s3_prefix,
    save_schema_to_s3,
)

from products.data_warehouse.backend.s3 import get_s3_client


class TempStorageWriter:
    """Writes transformed PyArrow tables to temp S3 storage for the L workflow to consume."""

    def __init__(
        self,
        team_id: int,
        source_id: str,
        schema_id: str,
        job_id: str,
        table_name: str,
    ):
        self.team_id = team_id
        self.source_id = source_id
        self.schema_id = schema_id
        self.job_id = job_id
        self.table_name = table_name

        # Generate unique temp location
        self.temp_s3_prefix = generate_temp_s3_prefix(team_id, job_id)
        self.data_prefix = f"{self.temp_s3_prefix}/data"

        self.s3_client = get_s3_client()
        self.parquet_files: list[str] = []
        self.batch_info: list[dict] = []  # {path, row_count}
        self.total_rows = 0
        self.schema: pa.Schema | None = None
        self.schema_path: str | None = None
        self._part_counter = 0

    def write_batch(self, table: pa.Table) -> str:
        """Write a single PyArrow table batch to S3 as parquet. Returns the S3 path."""

        if self.schema is None:
            self.schema = table.schema
            self.schema_path = save_schema_to_s3(self.schema, self.temp_s3_prefix)

        part_file = f"{self.data_prefix}/part-{self._part_counter:04d}.parquet"
        self._part_counter += 1

        full_path = f"{settings.BUCKET_URL}/{part_file}"
        with self.s3_client.open(full_path, "wb") as f:
            pq.write_table(table, f, compression="snappy")

        row_count = table.num_rows
        self.parquet_files.append(part_file)
        self.batch_info.append({"path": part_file, "row_count": row_count})
        self.total_rows += row_count

        return part_file

    def get_schema_path(self) -> str | None:
        """Return the schema path (available after first batch is written)."""

        return self.schema_path

    def finalize(
        self,
        primary_keys: list[str] | None,
        partition_count: int | None,
        partition_keys: list[str] | None,
        partition_mode: str | None,
        sync_type: str,
        incremental_field: str | None,
        incremental_field_last_value: Any,
        incremental_field_earliest_value: Any,
        run_id: str,
        hogql_schema: dict[str, str],
    ) -> ETManifest:
        """Finalize the temp storage and create manifest."""

        if self.schema is None or self.schema_path is None:
            raise ValueError("No data written - schema is None")

        # Create manifest
        manifest = ETManifest(
            temp_s3_prefix=self.temp_s3_prefix,
            parquet_files=self.parquet_files,
            schema_path=self.schema_path,
            hogql_schema=hogql_schema,
            table_name=self.table_name,
            primary_keys=primary_keys,
            partition_count=partition_count,
            partition_keys=partition_keys,
            partition_mode=partition_mode,
            sync_type=sync_type,
            incremental_field=incremental_field,
            incremental_field_last_value=incremental_field_last_value,
            incremental_field_earliest_value=incremental_field_earliest_value,
            team_id=self.team_id,
            source_id=self.source_id,
            schema_id=self.schema_id,
            job_id=self.job_id,
            run_id=run_id,
            total_rows=self.total_rows,
            batch_info=self.batch_info,
        )

        manifest.save_to_s3()

        return manifest

    def cleanup(self) -> None:
        """Delete all temp files. Called by L workflow after successful completion."""
        try:
            self.s3_client.delete(f"{settings.BUCKET_URL}/{self.temp_s3_prefix}", recursive=True)
        except FileNotFoundError:
            pass


def cleanup_temp_storage(temp_s3_prefix: str) -> None:
    """Delete all temp files for a given prefix. Standalone function for use in activities."""
    s3_client = get_s3_client()
    try:
        s3_client.delete(f"{settings.BUCKET_URL}/{temp_s3_prefix}", recursive=True)
    except FileNotFoundError:
        pass
