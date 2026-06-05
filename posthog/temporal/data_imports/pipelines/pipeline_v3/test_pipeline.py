from typing import cast

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.data_imports.pipelines.pipeline_v3.pipeline import PipelineV3


def _make_logger() -> MagicMock:
    logger = MagicMock()
    logger.adebug = AsyncMock()
    logger.ainfo = AsyncMock()
    logger.awarning = AsyncMock()
    logger.aerror = AsyncMock()
    logger.exception = MagicMock()
    return logger


def _make_pipeline() -> PipelineV3:
    """Build a PipelineV3 with just enough wiring to exercise run()."""
    with patch.object(PipelineV3, "__init__", return_value=None):
        pipeline = PipelineV3.__new__(PipelineV3)

    pipeline._resource = MagicMock(name="test_table", primary_keys=["id"])
    pipeline._resource_name = "test_table"
    pipeline._job = MagicMock(team_id=1, workflow_run_id="run-abc", billable=False)
    pipeline._source = MagicMock(source_type="Postgres")
    pipeline._schema = MagicMock(
        id="schema-1",
        source_id="source-1",
        is_incremental=False,
        is_webhook=False,
        is_append=False,
        table=None,
    )
    pipeline._table = None
    pipeline._logger = _make_logger()
    pipeline._is_incremental = False
    pipeline._reset_pipeline = False
    pipeline._delta_table_helper = MagicMock(is_first_sync=True)
    pipeline._resumable_source_manager = None
    pipeline._internal_schema = MagicMock()
    pipeline._cdp_producer = MagicMock()
    pipeline._batcher = MagicMock()
    pipeline._load_id = 1
    pipeline._s3_batch_writer = MagicMock()
    pipeline._pg_producer = MagicMock(sync_type="full_refresh")
    pipeline._accumulated_pa_schema = None
    pipeline._batch_results = []
    pipeline._shutdown_monitor = MagicMock()

    return pipeline


class TestExtractionFailureDoesNotCleanupS3:
    @pytest.mark.asyncio
    async def test_s3_files_preserved_when_extraction_fails(self) -> None:
        pipeline = _make_pipeline()
        s3_writer = cast(MagicMock, pipeline._s3_batch_writer)

        with (
            patch(
                "posthog.temporal.data_imports.pipelines.pipeline_v3.pipeline.cdp_producer_clear_chunks",
                side_effect=RuntimeError("simulated extraction failure"),
            ),
            patch("posthog.temporal.data_imports.pipelines.pipeline_v3.pipeline.activity") as mock_activity,
        ):
            mock_activity.in_activity.return_value = False

            with pytest.raises(RuntimeError, match="simulated extraction failure"):
                await pipeline.run()

        s3_writer.cleanup.assert_not_called()


class TestFullRefreshDefersTableClearToLoad:
    @pytest.mark.asyncio
    async def test_v3_full_refresh_does_not_delete_s3_on_extract(self) -> None:
        # drives the real handle_reset_or_full_refresh: v3 must ask reset_table to skip the racy
        # S3 delete (delete_s3_data=False) and let the load's overwrite clear instead
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        pipeline = _make_pipeline()
        pipeline._schema.sync_type = ExternalDataSchema.SyncType.FULL_REFRESH
        reset_table = AsyncMock()
        cast(MagicMock, pipeline._delta_table_helper).reset_table = reset_table
        # stop run() right after reset/full-refresh handling so we don't drive extraction
        cast(MagicMock, pipeline._resource).items.side_effect = RuntimeError("stop after reset handling")

        module = "posthog.temporal.data_imports.pipelines.pipeline_v3.pipeline"
        extract = "posthog.temporal.data_imports.pipelines.common.extract"
        with (
            patch(f"{module}.cdp_producer_clear_chunks", new=AsyncMock()),
            patch(f"{module}.reset_rows_synced_if_needed", new=AsyncMock()),
            patch(f"{module}.setup_row_tracking_with_billing_check", new=AsyncMock()),
            patch(f"{extract}.database_sync_to_async_pool", new=lambda fn: AsyncMock()),
            patch(f"{module}.activity") as mock_activity,
        ):
            mock_activity.in_activity.return_value = False

            with pytest.raises(RuntimeError, match="stop after reset handling"):
                await pipeline.run()

        reset_table.assert_awaited_once_with(delete_s3_data=False)
