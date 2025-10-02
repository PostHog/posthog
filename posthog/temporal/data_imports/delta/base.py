import json
from abc import ABC, abstractmethod

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
from conditional_cache import lru_cache
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema

from posthog.exceptions_capture import capture_exception
from posthog.warehouse.s3 import ensure_bucket_exists, get_s3_client


class DeltaBase(ABC):
    @abstractmethod
    def _get_delta_table_uri(self) -> str:
        pass

    def _get_credentials(self):
        if not settings.AIRBYTE_BUCKET_KEY or not settings.AIRBYTE_BUCKET_SECRET or not settings.AIRBYTE_BUCKET_REGION:
            raise KeyError(
                "Missing env vars for data warehouse. Required vars: AIRBYTE_BUCKET_KEY, AIRBYTE_BUCKET_SECRET, AIRBYTE_BUCKET_REGION"
            )

        if settings.USE_LOCAL_SETUP:
            ensure_bucket_exists(
                settings.BUCKET_URL,
                settings.AIRBYTE_BUCKET_KEY,
                settings.AIRBYTE_BUCKET_SECRET,
                settings.OBJECT_STORAGE_ENDPOINT,
            )

            return {
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "endpoint_url": settings.OBJECT_STORAGE_ENDPOINT,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
                "AWS_ALLOW_HTTP": "true",
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            }

        return {
            "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
            "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
            "region_name": settings.AIRBYTE_BUCKET_REGION,
            "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
            "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
        }

    def _evolve_delta_schema(self, schema: pa.Schema) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()
        if delta_table is None:
            raise Exception("Deltalake table not found")

        delta_table_schema = delta_table.schema().to_pyarrow()

        new_fields = [
            deltalake.Field.from_pyarrow(field)
            for field in ensure_delta_compatible_arrow_schema(schema)
            if field.name not in delta_table_schema.names
        ]
        if new_fields:
            delta_table.alter.add_columns(new_fields)

        return delta_table

    @lru_cache(maxsize=1, condition=lambda result: result is not None)
    def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = self._get_delta_table_uri()
        storage_options = self._get_credentials()

        if deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
            try:
                return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)
            except Exception as e:
                # Temp fix for bugged tables
                capture_exception(e)
                raise

        return None

    def reset_table(self):
        delta_uri = self._get_delta_table_uri()

        s3 = get_s3_client()
        try:
            s3.delete(delta_uri, recursive=True)
        except FileNotFoundError:
            pass

        self.get_delta_table.cache_clear()

        self._logger.debug("reset_table: _is_first_sync=True")
        self._is_first_sync = True

    def compact_table(self) -> None:
        table = self.get_delta_table()
        if table is None:
            raise Exception("Deltatable not found")

        self._logger.debug("Compacting table...")
        compact_stats = table.optimize.compact()
        self._logger.debug(json.dumps(compact_stats))

        self._logger.debug("Vacuuming table...")
        vacuum_stats = table.vacuum(retention_hours=24, enforce_retention_duration=False, dry_run=False)
        self._logger.debug(json.dumps(vacuum_stats))

        self._logger.debug("Compacting and vacuuming complete")
