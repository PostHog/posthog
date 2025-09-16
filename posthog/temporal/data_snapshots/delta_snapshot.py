from datetime import UTC, datetime

from django.conf import settings

import pyarrow as pa
import deltalake as deltalake
from conditional_cache import lru_cache

from posthog.exceptions_capture import capture_exception
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.s3 import ensure_bucket_exists


class DeltaSnapshot:
    VALID_UNTIL_COLUMN: str = "valid_until"

    def __init__(self, saved_query: DataWarehouseSavedQuery):
        self.saved_query = saved_query

    def _get_delta_table_uri(self) -> str:
        return f"{settings.BUCKET_URL}/team_{self.saved_query.team.pk}_snapshot_{self.saved_query.id.hex}/snapshots/{self.saved_query.normalized_name}"

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

    @lru_cache(maxsize=1, condition=lambda result: result is not None)
    def get_delta_table(self) -> deltalake.DeltaTable | None:
        delta_uri = self._get_delta_table_uri()
        storage_options = self._get_credentials()

        if deltalake.DeltaTable.is_deltatable(table_uri=delta_uri, storage_options=storage_options):
            try:
                return deltalake.DeltaTable(table_uri=delta_uri, storage_options=storage_options)
            except Exception as e:
                capture_exception(e)

        return None

    @property
    def columns(self) -> list[str]:
        return self.saved_query.snapshot_config.get("fields", [])

    def snapshot(self, data: pa.Table):
        delta_table = self.get_delta_table()

        if delta_table is None:
            delta_table = deltalake.DeltaTable.create(
                table_uri=self._get_delta_table_uri(),
                schema=data.schema,
                storage_options=self._get_credentials(),
            )

        # Close out the latest rows from the snapshot
        now_micros = int(datetime.now(UTC).timestamp() * 1_000_000)

        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate="source.merge_key = target.merge_key",
            streamed_exec=True,
        ).when_matched_update(
            updates={
                # indicates update
                self.VALID_UNTIL_COLUMN: "source.snapshot_ts",
            },
            predicate="source.row_hash != target.row_hash AND target.{self.VALID_UNTIL_COLUMN} IS NULL",
        ).when_not_matched_by_source_update(
            updates={
                # indicates deletion
                self.VALID_UNTIL_COLUMN: f"to_timestamp_micros({now_micros})",
            },
            predicate=f"target.{self.VALID_UNTIL_COLUMN} IS NULL",
            # insert brand new rows
        ).when_not_matched_insert_all().execute()

        # Insert the updated rows
        delta_table.merge(
            source=data,
            source_alias="source",
            target_alias="target",
            predicate=f"source.merge_key = target.merge_key AND target.{self.VALID_UNTIL_COLUMN} IS NULL",
            streamed_exec=True,
        ).when_not_matched_insert_all().execute()
