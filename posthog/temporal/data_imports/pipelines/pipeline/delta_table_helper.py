from collections.abc import Sequence
from conditional_cache import lru_cache
from typing import Any
import deltalake.exceptions
import pyarrow as pa
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema
from dlt.common.normalizers.naming.snake_case import NamingConvention
import deltalake as deltalake
from django.conf import settings
from sentry_sdk import capture_exception
from posthog.settings.base_variables import TEST
from posthog.temporal.common.logger import FilteringBoundLogger
from posthog.warehouse.models import ExternalDataJob


class DeltaTableHelper:
    _resource_name: str
    _job: ExternalDataJob
    _logger: FilteringBoundLogger

    def __init__(self, resource_name: str, job: ExternalDataJob, logger: FilteringBoundLogger) -> None:
        self._resource_name = resource_name
        self._job = job
        self._logger = logger

    def _get_credentials(self):
        if TEST:
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

    def _get_delta_table_uri(self) -> str:
        normalized_resource_name = NamingConvention().normalize_identifier(self._resource_name)
        # Appended __v2 on to the end of the url so that data of the V2 pipeline isn't the same as V1
        return f"{settings.BUCKET_URL}/{self._job.folder_path()}/{normalized_resource_name}__v2"

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
            return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)

        return None

    def write_to_deltalake(
        self, data: pa.Table, is_incremental: bool, chunk_index: int, primary_keys: Sequence[Any] | None
    ) -> deltalake.DeltaTable:
        delta_table = self.get_delta_table()

        if delta_table:
            delta_table = self._evolve_delta_schema(data.schema)

        if is_incremental and delta_table is not None:
            if not primary_keys or len(primary_keys) == 0:
                raise Exception("Primary key required for incremental syncs")

            delta_table.merge(
                source=data,
                source_alias="source",
                target_alias="target",
                predicate=" AND ".join([f"source.{c} = target.{c}" for c in primary_keys]),
            ).when_matched_update_all().when_not_matched_insert_all().execute()
        else:
            mode = "append"
            schema_mode = "merge"
            if chunk_index == 0 or delta_table is None:
                mode = "overwrite"
                schema_mode = "overwrite"

            if delta_table is None:
                storage_options = self._get_credentials()
                delta_table = deltalake.DeltaTable.create(
                    table_uri=self._get_delta_table_uri(), schema=data.schema, storage_options=storage_options
                )
            try:
                deltalake.write_deltalake(
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=None,
                    mode=mode,
                    schema_mode=schema_mode,
                    engine="rust",
                )  # type: ignore
            except deltalake.exceptions.SchemaMismatchError as e:
                self._logger.debug("SchemaMismatchError: attempting to overwrite schema instead", exc_info=e)
                capture_exception(e)

                deltalake.write_deltalake(
                    table_or_uri=delta_table,
                    data=data,
                    partition_by=None,
                    mode=mode,
                    schema_mode="overwrite",
                    engine="rust",
                )  # type: ignore

        delta_table = self.get_delta_table()
        assert delta_table is not None

        return delta_table
