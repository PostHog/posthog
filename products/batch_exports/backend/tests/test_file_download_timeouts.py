import datetime as dt
from uuid import UUID

from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from temporalio import workflow
from temporalio.client import Client
from temporalio.common import MetricMeter

from products.batch_exports.backend import service
from products.batch_exports.backend.models.batch_export import BatchExportOnDemand
from products.batch_exports.backend.service import BatchExportModel, FileDownloadBatchExportInputs
from products.batch_exports.backend.temporal.destinations.file_download_batch_export import (
    FileDownloadBatchExportWorkflow,
    export_to_file_download_bucket_with_temporary_credentials,
)
from products.batch_exports.backend.temporal.destinations.s3_batch_export import S3BatchExportResult
from products.batch_exports.backend.temporal.pipeline.entrypoint import _get_config_for_interval
from products.batch_exports.backend.temporal.pipeline.internal_stage import (
    InternalStageResult,
    insert_into_internal_stage_activity,
)

START = dt.datetime(2026, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=2)))
END = START + dt.timedelta(hours=1)
EXPORT_ID = UUID("00000000-0000-4000-8000-000000000001")
RUN_ID = UUID("00000000-0000-4000-8000-000000000002")


class TestFileDownloadTimeouts(SimpleTestCase):
    @parameterized.expand(
        [
            ("neither_bound", None, None, 21600, 900),
            ("start_only", START, None, 21600, 900),
            ("end_only", None, END, 21600, 900),
            ("both_bounds", START, END, 28800, 1500),
            ("configured_budgets", None, None, 28800, 1500),
        ]
    )
    def test_service_pins_budgets_only_for_incomplete_intervals(
        self, _name: str, start: dt.datetime | None, end: dt.datetime | None, main_seconds: int, query_seconds: int
    ) -> None:
        batch_export = BatchExportOnDemand(id=EXPORT_ID, team_id=1)
        model = BatchExportModel(name="hogql", schema=None, hogql_query="SELECT 1 AS value")
        client = AsyncMock(spec=Client)

        with (
            override_settings(
                BATCH_EXPORT_HOGQL_ON_DEMAND_MAIN_TIMEOUT_SECONDS=main_seconds,
                BATCH_EXPORT_HOGQL_MAX_EXECUTION_TIME=query_seconds,
            ),
            patch.object(service, "sync_connect", return_value=client),
        ):
            service.start_file_download_batch_export(
                batch_export,
                "file-download-test",
                start,
                end,
                model,
                batch_export_run_id=RUN_ID,
            )

        client.start_workflow.assert_awaited_once()
        call = client.start_workflow.await_args
        assert call is not None
        assert call.args[0] == "file-download-export"
        assert call.kwargs["id"] == "file-download-test"
        inputs = call.args[1]
        assert isinstance(inputs, FileDownloadBatchExportInputs)
        assert inputs.data_interval_start == (start.isoformat() if start is not None else None)
        assert inputs.data_interval_end == (end.isoformat() if end is not None else None)
        assert inputs.batch_export_run_id == RUN_ID
        assert inputs.batch_export_model == model
        incomplete = start is None or end is None
        assert inputs.main_activity_timeout_seconds == (main_seconds if incomplete else None)
        assert inputs.stage_activity_timeout_seconds == (query_seconds + 300 if incomplete else None)

    @parameterized.expand(
        [
            ("events", "events", RUN_ID, None, None),
            ("events_start_only", "events", RUN_ID, START, None),
            ("events_end_only", "events", RUN_ID, None, END),
            ("not_on_demand", "hogql", None, None, None),
        ]
    )
    def test_service_rejects_incomplete_intervals_outside_on_demand_hogql(
        self, _name: str, model_name: str, run_id: UUID | None, start: dt.datetime | None, end: dt.datetime | None
    ) -> None:
        with patch.object(service, "sync_connect") as connect:
            with self.assertRaisesRegex(ValueError, "Only on-demand HogQL exports"):
                service.start_file_download_batch_export(
                    BatchExportOnDemand(id=EXPORT_ID, team_id=1),
                    "file-download-test",
                    start,
                    end,
                    BatchExportModel(name=model_name, schema=None),
                    batch_export_run_id=run_id,
                )
            connect.assert_not_called()

    @parameterized.expand(
        [
            ("explicit_budgets", 21600, 1200, 0, 21600),
            ("main_override", 21600, 1200, 28800, 28800),
            ("smaller_override", 21600, 1200, 60, 21600),
            ("independent_stage_budget", 21600, 1800, 0, 21600),
        ]
    )
    def test_interval_free_budgets_are_independent(
        self, _name: str, main_seconds: int, stage_seconds: int, override_seconds: int, expected_main_seconds: int
    ) -> None:
        config = _get_config_for_interval(
            None,
            dt.timedelta(seconds=override_seconds),
            main_activity_timeout_seconds=main_seconds,
            stage_activity_timeout_seconds=stage_seconds,
        )

        assert config.main_start_to_close == dt.timedelta(seconds=expected_main_seconds)
        assert config.stage_start_to_close == dt.timedelta(seconds=stage_seconds)
        assert config.failure_check_window == 50

    @parameterized.expand(
        [
            ("hour", 21600, 3600, 24),
            ("day", 86400, 21600, 7),
            ("week", 259200, 86400, 4),
            ("every 5 minutes", 1200, 1200, 12),
            ("every 3600 seconds", 3600, 3600, 50),
        ]
    )
    def test_existing_intervals_ignore_explicit_budgets(
        self, interval: str, main_seconds: int, stage_seconds: int, failure_check_window: int
    ) -> None:
        config = _get_config_for_interval(
            interval,
            dt.timedelta(0),
            main_activity_timeout_seconds=400000,
            stage_activity_timeout_seconds=300000,
        )

        assert config.main_start_to_close == dt.timedelta(seconds=main_seconds)
        assert config.stage_start_to_close == dt.timedelta(seconds=stage_seconds)
        assert config.failure_check_window == failure_check_window

    @parameterized.expand(
        [
            ("neither_bound", None, None, 28800, 1800),
            ("start_only", START.isoformat(), None, 28800, 1800),
            ("end_only", None, END.isoformat(), 28800, 1800),
            ("both_bounds", START.isoformat(), END.isoformat(), 3600, 3600),
        ]
    )
    async def test_workflow_dispatch_preserves_bounds_and_persisted_budgets(
        self, _name: str, start: str | None, end: str | None, main_seconds: int, stage_seconds: int
    ) -> None:
        inputs = FileDownloadBatchExportInputs(
            batch_export_id=str(EXPORT_ID),
            team_id=1,
            batch_export_run_id=RUN_ID,
            batch_export_model=BatchExportModel(name="hogql", schema=None, hogql_query="SELECT 1 AS value"),
            data_interval_start=start,
            data_interval_end=end,
            main_activity_timeout_seconds=28800,
            stage_activity_timeout_seconds=1800,
        )
        with (
            override_settings(
                BATCH_EXPORT_HOGQL_ON_DEMAND_MAIN_TIMEOUT_SECONDS=21600,
                BATCH_EXPORT_HOGQL_MAX_EXECUTION_TIME=900,
            ),
            patch.object(workflow, "info", return_value=Mock(workflow_id="file-download-test")),
            patch.object(workflow, "metric_meter", return_value=MetricMeter.noop),
            patch.object(workflow, "set_current_details"),
            patch.object(
                workflow,
                "execute_activity",
                new_callable=AsyncMock,
                side_effect=[
                    InternalStageResult(stage_folder="test-stage", records_total=1),
                    S3BatchExportResult(records_completed=1, bytes_exported=10),
                    None,
                    [],
                ],
            ) as execute_activity,
        ):
            result = await FileDownloadBatchExportWorkflow().run(inputs)

        activity_calls = {call.args[0]: call for call in execute_activity.await_args_list}
        stage_call = activity_calls[insert_into_internal_stage_activity]
        export_call = activity_calls[export_to_file_download_bucket_with_temporary_credentials]
        for activity_inputs in (stage_call.args[1], export_call.args[1].batch_export):
            assert activity_inputs.data_interval_start == start
            assert activity_inputs.data_interval_end == end
            assert activity_inputs.run_id == str(RUN_ID)
            assert activity_inputs.on_demand is True
        assert stage_call.kwargs["start_to_close_timeout"] == dt.timedelta(seconds=stage_seconds)
        assert export_call.kwargs["start_to_close_timeout"] == dt.timedelta(seconds=main_seconds)
        assert result.records_completed == 1
        assert result.bytes_exported == 10
        assert result.error is None
