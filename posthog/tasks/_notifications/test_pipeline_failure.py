import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.batch_exports.models import BatchExport, BatchExportDestination, BatchExportRun
from posthog.models import OrganizationMembership
from posthog.models.plugin import Plugin, PluginConfig
from posthog.tasks._notifications.pipeline_failure import (
    dispatch_batch_export_failure_realtime,
    dispatch_pipeline_failure_realtime,
    dispatch_plugin_disabled_realtime,
)


class TestDispatchPipelineFailureRealtime(BaseTest):
    @patch("posthog.tasks._notifications.pipeline_failure.create_notification")
    def test_dispatches_one_notification_per_membership(self, mock_create_notification):
        user2 = self._create_user("subscriber@test.com")
        memberships = list(
            OrganizationMembership.objects.filter(organization=self.organization, user__in=[self.user, user2])
        )

        dispatch_pipeline_failure_realtime(
            team=self.team,
            memberships=memberships,
            title="Plugin foo disabled",
            body="boom",
            resource_id="42",
            source_url="/project/1/pipeline/transformations/42",
        )

        assert mock_create_notification.call_count == 2
        targets = sorted(call.args[0].target_id for call in mock_create_notification.call_args_list)
        assert targets == sorted([str(self.user.id), str(user2.id)])

    @patch("posthog.tasks._notifications.pipeline_failure.create_notification", side_effect=RuntimeError("kafka"))
    def test_swallows_exceptions(self, _mock_create):
        memberships = list(OrganizationMembership.objects.filter(user=self.user, organization=self.organization))
        dispatch_pipeline_failure_realtime(
            team=self.team,
            memberships=memberships,
            title="x",
            body="y",
            resource_id="1",
            source_url="/",
        )


class TestDispatchPluginDisabledRealtime(BaseTest):
    @patch("posthog.tasks._notifications.pipeline_failure.dispatch_pipeline_failure_realtime")
    def test_dispatches_for_plugin(self, mock_realtime):
        plugin = Plugin.objects.create(organization=self.organization)
        plugin_config = PluginConfig.objects.create(plugin=plugin, team=self.team, enabled=True, order=1)

        dispatch_plugin_disabled_realtime(plugin_config.id, "boom")

        mock_realtime.assert_called_once()
        kwargs = mock_realtime.call_args.kwargs
        assert kwargs["team"].id == self.team.id
        assert "Plugin" in kwargs["title"]
        assert kwargs["resource_id"] == str(plugin_config.id)
        assert kwargs["body"] == "boom"

    @patch("posthog.tasks._notifications.pipeline_failure.dispatch_pipeline_failure_realtime")
    def test_swallows_missing_plugin_config(self, mock_realtime):
        dispatch_plugin_disabled_realtime(999_999_999, "boom")
        mock_realtime.assert_not_called()


class TestDispatchBatchExportFailureRealtime(BaseTest):
    @patch("posthog.tasks._notifications.pipeline_failure.dispatch_pipeline_failure_realtime")
    def test_dispatches_for_batch_export_run(self, mock_realtime):
        batch_export_destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.S3, config={"bucket_name": "my_production_s3_bucket"}
        )
        batch_export = BatchExport.objects.create(  # type: ignore
            team=self.team, name="A batch export", destination=batch_export_destination
        )
        now = dt.datetime.now()
        batch_export_run = BatchExportRun.objects.create(
            batch_export=batch_export,
            status=BatchExportRun.Status.FAILED,
            data_interval_start=now - dt.timedelta(hours=1),
            data_interval_end=now,
        )

        dispatch_batch_export_failure_realtime(batch_export_run.id)

        mock_realtime.assert_called_once()
        kwargs = mock_realtime.call_args.kwargs
        assert kwargs["team"].id == self.team.id
        assert "Batch export" in kwargs["title"]
        assert batch_export.name in kwargs["title"]
        assert kwargs["resource_id"] == str(batch_export.id)
