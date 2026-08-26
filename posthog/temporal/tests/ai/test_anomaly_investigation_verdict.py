"""Verifies that the workflow activity persists the agent's verdict onto the AlertCheck."""

import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.schema import AlertState

from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.runner import InvestigationRunResult
from posthog.temporal.ai.anomaly_investigation.workflow import (
    AnomalyInvestigationWorkflowInputs,
    investigate_anomaly_activity,
)

from products.alerts.backend.models.alert import (
    AlertCheck,
    AlertConfiguration,
    InvestigationStatus,
    InvestigationVerdict,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.exports.backend.models.exported_asset import ExportedAsset
from products.product_analytics.backend.facade.models import Insight


class TestInvestigationVerdictPersistence(NonAtomicBaseTest):
    # NonAtomicBaseTest TRUNCATEs after each test so class-level fixtures stale out;
    # force per-test setup so self.team is freshly inserted each time.
    CLASS_DATA_LEVEL_SETUP = False

    def _create_slack_destination(self) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name="Slack #alerts",
            type="internal_destination",
            template_id="template-slack",
            enabled=True,
            filters={
                "events": [{"id": "$insight_alert_firing", "type": "events"}],
                "properties": [{"key": "alert_id", "value": str(self.alert.id), "operator": "exact", "type": "event"}],
            },
        )

    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            state=AlertState.FIRING,
            created_by=self.user,
        )
        self.alert_check = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.FIRING,
            calculated_value=42.0,
        )

    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.anomaly_investigation.workflow._prepare_insight_chart_url", return_value=None)
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_true_positive_verdict_is_persisted(self, mock_info, _heartbeat, mock_run, _prepare) -> None:
        mock_info.return_value.heartbeat_timeout = None
        mock_run.return_value = InvestigationRunResult(
            report=InvestigationReport(
                verdict="true_positive",
                summary="Confirmed spike caused by campaign launch.",
                hypotheses=[],
                recommendations=[],
            ),
            tool_calls_used=0,
            model="test-model",
        )

        await investigate_anomaly_activity(
            AnomalyInvestigationWorkflowInputs(
                team_id=self.team.id,
                alert_id=self.alert.id,
                alert_check_id=self.alert_check.id,
                user_id=self.user.id,
            )
        )

        await sync_to_async(self.alert_check.refresh_from_db)()
        assert self.alert_check.investigation_status == InvestigationStatus.DONE
        assert self.alert_check.investigation_verdict == InvestigationVerdict.TRUE_POSITIVE
        assert self.alert_check.investigation_summary == "Confirmed spike caused by campaign launch."
        assert self.alert_check.investigation_notebook_id is not None

    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.exports.render_png_export")
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_false_positive_verdict_is_persisted(self, mock_info, _heartbeat, mock_run, mock_render) -> None:
        await sync_to_async(self._create_slack_destination)()
        mock_info.return_value.heartbeat_timeout = None
        mock_run.return_value = InvestigationRunResult(
            report=InvestigationReport(
                verdict="false_positive",
                summary="Spike was a replay of duplicated events from a broken SDK release.",
                hypotheses=[],
                recommendations=[],
            ),
            tool_calls_used=0,
            model="test-model",
        )

        await investigate_anomaly_activity(
            AnomalyInvestigationWorkflowInputs(
                team_id=self.team.id,
                alert_id=self.alert.id,
                alert_check_id=self.alert_check.id,
                user_id=self.user.id,
            )
        )

        await sync_to_async(self.alert_check.refresh_from_db)()
        assert self.alert_check.investigation_verdict == InvestigationVerdict.FALSE_POSITIVE
        # A suppressed notification must not pay for a chart render.
        mock_render.assert_not_called()

    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.anomaly_investigation.workflow._prepare_insight_chart_url", return_value=None)
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.signals.emit_signal")
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_completed_investigation_emits_signal(
        self, mock_info, _heartbeat, mock_run, mock_emit, _prepare
    ) -> None:
        mock_info.return_value.heartbeat_timeout = None
        mock_run.return_value = InvestigationRunResult(
            report=InvestigationReport(
                verdict="true_positive",
                summary="Confirmed spike caused by campaign launch.",
                hypotheses=[],
                recommendations=[],
            ),
            tool_calls_used=0,
            model="test-model",
        )

        await investigate_anomaly_activity(
            AnomalyInvestigationWorkflowInputs(
                team_id=self.team.id,
                alert_id=self.alert.id,
                alert_check_id=self.alert_check.id,
                user_id=self.user.id,
            )
        )

        mock_emit.assert_awaited_once()
        kwargs = mock_emit.await_args.kwargs
        assert kwargs["source_product"] == "analytics"
        assert kwargs["source_type"] == "anomaly_investigation"
        assert kwargs["source_id"] == str(self.alert_check.id)
        assert kwargs["weight"] == 1
        assert kwargs["extra"]["verdict"] == "true_positive"
        assert kwargs["extra"]["insight_id"] == str(self.insight.id)
        assert not {"summary", "hypotheses", "recommendations", "tool_calls_used"} & kwargs["extra"].keys()

    @pytest.mark.asyncio
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.dispatch_alert_notification", return_value=[])
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.exports.render_png_export")
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_notification_carries_insight_chart_url(
        self, mock_info, _heartbeat, mock_run, mock_render, mock_dispatch
    ) -> None:
        mock_info.return_value.heartbeat_timeout = None
        mock_run.return_value = InvestigationRunResult(
            report=InvestigationReport(
                verdict="true_positive",
                summary="Confirmed spike caused by campaign launch.",
                hypotheses=[],
                recommendations=[],
            ),
            tool_calls_used=0,
            model="test-model",
        )
        await sync_to_async(self._create_slack_destination)()
        asset = await sync_to_async(ExportedAsset.objects.create)(
            team=self.team,
            insight=self.insight,
            export_format=ExportedAsset.ExportFormat.PNG,
            content=b"png-bytes",
        )
        mock_render.return_value = (asset, b"png-bytes")

        await investigate_anomaly_activity(
            AnomalyInvestigationWorkflowInputs(
                team_id=self.team.id,
                alert_id=self.alert.id,
                alert_check_id=self.alert_check.id,
                user_id=self.user.id,
            )
        )

        assert mock_render.call_args.kwargs["insight_id"] == self.insight.id
        assert mock_render.call_args.kwargs["is_system"] is True
        extra_properties = mock_dispatch.call_args.kwargs["extra_properties"]
        assert "/exporter/" in extra_properties["insight_chart_url"]
        assert "token=" in extra_properties["insight_chart_url"]
