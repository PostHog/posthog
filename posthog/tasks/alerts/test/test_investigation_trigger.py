"""Tests for the investigation-agent trigger in posthog/tasks/alerts/checks.py.

Focus is the branching logic around when the workflow gets enqueued — not the
agent itself. The workflow is mocked at the enqueue seam.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import AlertState

from posthog.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from posthog.tasks.alerts.checks import _maybe_start_investigation_agent


class TestInvestigationTrigger(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        from posthog.models import Insight

        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            state=AlertState.FIRING,
        )

    def _make_check(self, *, state: str = AlertState.FIRING, investigation_status: str | None = None) -> AlertCheck:
        return AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=state,
            calculated_value=42.0,
            investigation_status=investigation_status,
        )

    @patch("posthog.tasks.alerts.checks.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_enqueues_on_transition_to_firing(self, mock_start: Any, _on_commit: Any) -> None:
        check = self._make_check()
        _maybe_start_investigation_agent(self.alert, check, previous_state=AlertState.NOT_FIRING)
        mock_start.assert_called_once_with(self.alert, check)
        check.refresh_from_db()
        # _start_investigation_workflow is mocked so status stays at PENDING (set before enqueue).
        assert check.investigation_status == InvestigationStatus.PENDING

    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_does_not_enqueue_when_already_firing(self, mock_start: Any) -> None:
        check = self._make_check()
        _maybe_start_investigation_agent(self.alert, check, previous_state=AlertState.FIRING)
        mock_start.assert_not_called()

    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_does_not_enqueue_when_not_opted_in(self, mock_start: Any) -> None:
        self.alert.investigation_agent_enabled = False
        self.alert.save()
        check = self._make_check()
        _maybe_start_investigation_agent(self.alert, check, previous_state=AlertState.NOT_FIRING)
        mock_start.assert_not_called()

    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_does_not_enqueue_for_threshold_only_alerts(self, mock_start: Any) -> None:
        self.alert.detector_config = None
        self.alert.save()
        check = self._make_check()
        _maybe_start_investigation_agent(self.alert, check, previous_state=AlertState.NOT_FIRING)
        mock_start.assert_not_called()

    @patch("posthog.tasks.alerts.checks.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_cooldown_skips_when_recent_investigation_exists(self, mock_start: Any, _on_commit: Any) -> None:
        now = datetime(2024, 6, 2, 10, 0, tzinfo=UTC)
        # Earlier investigation 10 minutes ago — well inside the 1h cooldown.
        with freeze_time(now - timedelta(minutes=10)):
            self._make_check(state=AlertState.FIRING, investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            newer_check = self._make_check()
            _maybe_start_investigation_agent(self.alert, newer_check, previous_state=AlertState.NOT_FIRING)

        mock_start.assert_not_called()
        newer_check.refresh_from_db()
        assert newer_check.investigation_status == InvestigationStatus.SKIPPED

    @patch("posthog.tasks.alerts.checks.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("posthog.tasks.alerts.checks._start_investigation_workflow")
    def test_cooldown_allows_after_expiry(self, mock_start: Any, _on_commit: Any) -> None:
        now = datetime(2024, 6, 2, 10, 0, tzinfo=UTC)
        # Earlier investigation 2 hours ago — outside the 1h cooldown.
        with freeze_time(now - timedelta(hours=2)):
            self._make_check(state=AlertState.FIRING, investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            newer_check = self._make_check()
            _maybe_start_investigation_agent(self.alert, newer_check, previous_state=AlertState.NOT_FIRING)

        mock_start.assert_called_once()

    @patch("posthog.tasks.alerts.checks.transaction.on_commit", side_effect=lambda cb: cb())
    @patch("posthog.tasks.alerts.checks._start_investigation_workflow", side_effect=RuntimeError("temporal down"))
    def test_marks_failed_when_enqueue_raises(self, _mock_start: Any, _on_commit: Any) -> None:
        check = self._make_check()
        _maybe_start_investigation_agent(self.alert, check, previous_state=AlertState.NOT_FIRING)
        check.refresh_from_db()
        assert check.investigation_status == InvestigationStatus.FAILED
        assert check.investigation_error is not None
        assert "temporal down" in check.investigation_error["message"]
