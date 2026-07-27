import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models.utils import UUIDT

from products.batch_exports.backend.models.batch_export import BatchExport, BatchExportDestination, BatchExportRun
from products.batch_exports.backend.temporal.batch_exports import _dispatch_batch_export_failure_realtime


class TestDispatchBatchExportFailureRealtime(BaseTest):
    @patch("products.batch_exports.backend.temporal.batch_exports.create_notification")
    def test_dispatches_for_failed_batch_export_run(self, mock_create_notification: MagicMock) -> None:
        destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_bucket"}
        )
        batch_export = BatchExport.objects.create(team=self.team, name="A batch export", destination=destination)
        now = dt.datetime.now()
        batch_export_run = BatchExportRun.objects.create(
            batch_export=batch_export,
            status=BatchExportRun.Status.FAILED,
            data_interval_start=now - dt.timedelta(hours=1),
            data_interval_end=now,
        )

        _dispatch_batch_export_failure_realtime(batch_export_run.id)

        assert mock_create_notification.call_count >= 1
        first = mock_create_notification.call_args_list[0].args[0]
        assert first.notification_type.value == "pipeline_failure"
        assert "Batch export A batch export failed" in first.title
        assert first.resource_id == str(batch_export.id)
        assert first.source_url == f"/project/{self.team.project_id}/pipeline/batch-exports/{batch_export.id}"

    @patch(
        "products.batch_exports.backend.temporal.batch_exports.create_notification",
        side_effect=RuntimeError("kafka"),
    )
    def test_swallows_per_recipient_exceptions(self, mock_create: MagicMock) -> None:
        destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_bucket"}
        )
        batch_export = BatchExport.objects.create(team=self.team, name="A batch export", destination=destination)
        now = dt.datetime.now()
        batch_export_run = BatchExportRun.objects.create(
            batch_export=batch_export,
            status=BatchExportRun.Status.FAILED,
            data_interval_start=now - dt.timedelta(hours=1),
            data_interval_end=now,
        )
        # Should not raise.
        _dispatch_batch_export_failure_realtime(batch_export_run.id)
        # Confirms the function actually attempted the dispatch before swallowing,
        # so a silent early-return would not mask a regression here.
        assert mock_create.call_count >= 1

    @patch("products.batch_exports.backend.temporal.batch_exports.create_notification")
    def test_swallows_missing_run(self, mock_create_notification: MagicMock) -> None:
        _dispatch_batch_export_failure_realtime(str(UUIDT()))
        mock_create_notification.assert_not_called()
