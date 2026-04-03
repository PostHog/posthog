from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Optional

from django.conf import settings

import orjson
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from posthog.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list

from products.data_warehouse.backend.s3 import aget_s3_client

WAREHOUSE_WEBHOOK_FLAG = "warehouse-source-webhooks"


class WebhookSourceManager:
    _inputs: SourceInputs
    _logger: FilteringBoundLogger

    def __init__(self, inputs: SourceInputs, logger: FilteringBoundLogger) -> None:
        self._inputs = inputs
        self._logger = logger

    def _get_webhook_s3_prefix(self) -> str:
        return f"s3://{settings.DATAWAREHOUSE_BUCKET}/source_webhook_producer/{self._inputs.team_id}/{self._inputs.schema_id}"

    def _strip_s3_protocol(self, s3_path: str) -> str:
        return s3_path.replace("s3://", "")

    async def webhook_enabled(self) -> bool:
        from posthog.models.hog_functions.hog_function import HogFunction

        from products.data_warehouse.backend.models import ExternalDataSchema

        flag_enabled = await self._is_webhook_feature_flag_enabled()

        if not flag_enabled:
            return False

        schema = await database_sync_to_async_pool(ExternalDataSchema.objects.get)(
            id=self._inputs.schema_id, team_id=self._inputs.team_id
        )

        if not schema.is_webhook or not schema.initial_sync_complete or self._inputs.reset_pipeline:
            return False

        has_webhook_function = await database_sync_to_async_pool(
            HogFunction.objects.filter(
                inputs__source_id__value=self._inputs.source_id,
                team_id=self._inputs.team_id,
                type="warehouse_source_webhook",
                enabled=True,
                deleted=False,
            ).exists
        )()

        return has_webhook_function

    async def _list_webhook_parquet_files(self) -> list[str]:
        prefix = self._get_webhook_s3_prefix()

        async with aget_s3_client() as s3:
            try:
                ls_res = await s3._ls(prefix, detail=True)
                ls_values = ls_res.values() if isinstance(ls_res, dict) else ls_res
                files = [
                    f"s3://{f['Key']}" for f in ls_values if f["type"] != "directory" and f["Key"].endswith(".parquet")
                ]

                await self._logger.adebug("list_webhook_parquet_files", prefix=prefix, file_count=len(files))

                return files
            except FileNotFoundError:
                await self._logger.adebug("webhook_folder_not_found", prefix=prefix)
                return []

    async def get_items(
        self, table_transformer: Optional[Callable[[pa.Table], pa.Table]] = None
    ) -> AsyncGenerator[pa.Table]:
        files = await self._list_webhook_parquet_files()

        await self._logger.adebug(f"Webhook source reading {len(files)} files")

        async with aget_s3_client() as s3:
            for file in files:
                path = self._strip_s3_protocol(file)

                await self._logger.adebug(f"Webhook source reading file {path}")
                async with await s3.open_async(path, "rb") as f:
                    data = await f.read()
                    table = pq.read_table(pa.BufferReader(data))

                table = await self._validate_webhook_table(table)
                if table.num_rows == 0:
                    await self._logger.adebug("webhook_file_has_no_valid_rows", path=path)
                    await s3._rm(path)
                    continue

                table = self._transform_webhook_table(table)

                if table_transformer:
                    table = table_transformer(table)

                yield table

                await s3._rm(path)

    async def _validate_webhook_table(self, table: pa.Table) -> pa.Table:
        expected_team_id = self._inputs.team_id
        expected_schema_id = str(self._inputs.schema_id)

        team_id_match = pc.equal(table.column("team_id"), expected_team_id)
        schema_id_match = pc.equal(table.column("schema_id"), expected_schema_id)
        valid_mask = pc.and_(team_id_match, schema_id_match)

        filtered = table.filter(valid_mask)
        dropped = table.num_rows - filtered.num_rows
        if dropped > 0:
            await self._logger.adebug(
                "webhook_rows_filtered",
                dropped=dropped,
                expected_team_id=expected_team_id,
                expected_schema_id=expected_schema_id,
            )

        return filtered

    def _transform_webhook_table(self, table: pa.Table) -> pa.Table:
        rows = [orjson.loads(str(s)) for s in table.column("payload_json").to_pylist()]
        return table_from_py_list(rows)

    async def _is_webhook_feature_flag_enabled(self) -> bool:
        from posthog.models import Team

        try:
            team = await database_sync_to_async_pool(Team.objects.only("uuid", "organization_id").get)(
                id=self._inputs.team_id
            )
        except Team.DoesNotExist:
            return False

        try:
            enabled = await database_sync_to_async_pool(posthoganalytics.feature_enabled)(
                WAREHOUSE_WEBHOOK_FLAG,
                str(team.uuid),
                groups={
                    "organization": str(team.organization_id),
                    "project": str(team.id),
                },
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )

            if enabled:
                await self._logger.adebug(
                    f"Feature flag '{WAREHOUSE_WEBHOOK_FLAG}' is enabled for team {self._inputs.team_id}"
                )

            return bool(enabled)
        except Exception as e:
            capture_exception(e)
            return False
