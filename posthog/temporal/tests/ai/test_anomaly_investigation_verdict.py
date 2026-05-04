"""Verifies that the workflow activity persists the agent's verdict onto the AlertCheck."""

import pytest
from posthog.test.base import NonAtomicBaseTest
from unittest.mock import patch

from asgiref.sync import sync_to_async

from posthog.schema import AlertState

from posthog.models import Insight
from posthog.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus, InvestigationVerdict
from posthog.temporal.ai.anomaly_investigation.report import InvestigationReport
from posthog.temporal.ai.anomaly_investigation.runner import InvestigationRunResult
from posthog.temporal.ai.anomaly_investigation.workflow import (
    AnomalyInvestigationWorkflowInputs,
    investigate_anomaly_activity,
)


class TestInvestigationVerdictPersistence(NonAtomicBaseTest):
    # NonAtomicBaseTest TRUNCATEs after each test so class-level fixtures stale out;
    # force per-test setup so self.team is freshly inserted each time.
    CLASS_DATA_LEVEL_SETUP = False

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
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_true_positive_verdict_is_persisted(self, mock_info, _heartbeat, mock_run) -> None:
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
    @patch("posthog.temporal.ai.anomaly_investigation.workflow.run_investigation")
    @patch("temporalio.activity.heartbeat")
    @patch("temporalio.activity.info")
    async def test_false_positive_verdict_is_persisted(self, mock_info, _heartbeat, mock_run) -> None:
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
