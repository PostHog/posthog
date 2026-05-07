from uuid import uuid4

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.data_imports.pipelines.pipeline.pipeline import PipelineResult
from posthog.temporal.data_imports.pipelines.pipeline_sync import PipelineInputs
from posthog.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    _run_posthog_mwh_import,
)

from products.data_warehouse.backend.models import DataWarehouseTable


@pytest.mark.asyncio
class TestRunPostHogMWHImport:
    @patch(
        "posthog.temporal.data_imports.pipelines.pipeline_sync.validate_schema_and_update_table", new_callable=AsyncMock
    )
    @patch("posthog.temporal.data_imports.util.prepare_s3_files_for_querying", new_callable=AsyncMock)
    @patch(
        "posthog.temporal.data_imports.sources.posthog_mwh.posthog_mwh.get_mwh_row_count",
        return_value=1500,
    )
    @patch(
        "posthog.temporal.data_imports.sources.posthog_mwh.posthog_mwh.get_mwh_columns",
        return_value=[("id", "integer", False), ("amount", "numeric", True), ("created_at", "timestamp", False)],
    )
    @patch(
        "posthog.temporal.data_imports.sources.posthog_mwh.posthog_mwh.copy_mwh_table_to_s3",
        return_value="s3://data-warehouse/data-warehouse/team_1_posthogmwh_abc123/revenue_orders/",
    )
    @patch("products.data_warehouse.backend.s3.aget_s3_client")
    async def test_copy_to_s3_and_register_table(
        self,
        mock_s3_client,
        mock_copy,
        mock_columns,
        mock_row_count,
        mock_prepare,
        mock_validate,
    ):
        schema_id = uuid4()
        source_id = uuid4()

        mock_schema = MagicMock()
        mock_schema.name = "revenue.orders"
        mock_schema.id = schema_id

        mock_model = MagicMock()
        mock_model.folder_path.return_value = "team_1_posthogmwh_abc123"

        mock_logger = MagicMock()
        mock_logger.ainfo = AsyncMock()
        mock_logger.awarning = AsyncMock()

        mock_inputs = ImportDataActivityInputs(
            team_id=1,
            schema_id=schema_id,
            source_id=source_id,
            run_id="job-123",
        )

        job_inputs = PipelineInputs(
            source_id=str(source_id),
            schema_id=str(schema_id),
            run_id="job-123",
            team_id=1,
            job_type="PostHogMWH",
            dataset_name="team_1_posthogmwh_abc123",
        )

        s3_mock = AsyncMock()
        s3_mock._find = AsyncMock(
            return_value=[
                "data-warehouse/team_1_posthogmwh_abc123/revenue_orders/data_0.parquet",
                "data-warehouse/team_1_posthogmwh_abc123/revenue_orders/data_1.parquet",
            ]
        )
        mock_s3_client.return_value.__aenter__ = AsyncMock(return_value=s3_mock)
        mock_s3_client.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_prepare.return_value = "revenue_orders__query_1234567890"

        result = await _run_posthog_mwh_import(
            job_inputs=job_inputs,
            model=mock_model,
            schema=mock_schema,
            logger=mock_logger,
            inputs=mock_inputs,
        )

        assert result == PipelineResult(should_trigger_cdp_producer=False)

        mock_copy.assert_called_once()
        call_kwargs = mock_copy.call_args
        assert call_kwargs[1]["team_id"] == 1 or call_kwargs[0][0] == 1
        assert "revenue" in str(call_kwargs)
        assert "orders" in str(call_kwargs)

        mock_validate.assert_called_once()
        validate_kwargs = mock_validate.call_args.kwargs
        assert validate_kwargs["run_id"] == "job-123"
        assert validate_kwargs["team_id"] == 1
        assert validate_kwargs["schema_id"] == schema_id
        assert validate_kwargs["row_count"] == 1500
        assert validate_kwargs["table_format"] == DataWarehouseTable.TableFormat.Parquet
        assert validate_kwargs["queryable_folder"] == "revenue_orders__query_1234567890"
        assert validate_kwargs["table_schema_dict"] == {
            "id": "integer",
            "amount": "numeric",
            "created_at": "timestamp",
        }

    @patch(
        "posthog.temporal.data_imports.sources.posthog_mwh.posthog_mwh.copy_mwh_table_to_s3",
        return_value="s3://bucket/path/",
    )
    @patch("products.data_warehouse.backend.s3.aget_s3_client")
    async def test_no_parquet_files_skips_registration(
        self,
        mock_s3_client,
        mock_copy,
    ):
        schema_id = uuid4()

        mock_schema = MagicMock()
        mock_schema.name = "revenue.orders"
        mock_schema.id = schema_id

        mock_model = MagicMock()
        mock_model.folder_path.return_value = "team_1_posthogmwh_abc123"

        mock_logger = MagicMock()
        mock_logger.ainfo = AsyncMock()
        mock_logger.awarning = AsyncMock()

        mock_inputs = ImportDataActivityInputs(
            team_id=1,
            schema_id=schema_id,
            source_id=uuid4(),
            run_id="job-456",
        )

        job_inputs = PipelineInputs(
            source_id=str(mock_inputs.source_id),
            schema_id=str(schema_id),
            run_id="job-456",
            team_id=1,
            job_type="PostHogMWH",
            dataset_name="team_1_posthogmwh_abc123",
        )

        s3_mock = AsyncMock()
        s3_mock._find = AsyncMock(return_value=[])
        mock_s3_client.return_value.__aenter__ = AsyncMock(return_value=s3_mock)
        mock_s3_client.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await _run_posthog_mwh_import(
            job_inputs=job_inputs,
            model=mock_model,
            schema=mock_schema,
            logger=mock_logger,
            inputs=mock_inputs,
        )

        assert result == PipelineResult(should_trigger_cdp_producer=False)

    async def test_invalid_schema_name_raises(self):
        mock_schema = MagicMock()
        mock_schema.name = "no_dot_in_name"

        with pytest.raises(ValueError, match="schema.table"):
            await _run_posthog_mwh_import(
                job_inputs=MagicMock(),
                model=MagicMock(),
                schema=mock_schema,
                logger=MagicMock(),
                inputs=MagicMock(),
            )
