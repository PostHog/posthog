from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import AlertState

from posthog.models import AlertConfiguration, Insight
from posthog.models.alert import AlertCheck, InvestigationStatus
from posthog.tasks.alerts.investigation_notifications import (
    INVESTIGATION_NOTIFY_GRACE_MINUTES,
    INVESTIGATION_RUNNING_GRACE_MINUTES,
    run_investigation_notification_safety_net,
)

NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)


@freeze_time(NOW)
class TestInvestigationNotificationSafetyNet(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            investigation_gates_notifications=True,
            state=AlertState.FIRING,
            enabled=True,
            created_by=self.user,
        )

    def _make_check(
        self,
        *,
        age_minutes: int,
        investigation_status: str | None = None,
        notification_sent_at: datetime | None = None,
        notification_suppressed_by_agent: bool = False,
        targets_notified: dict | None = None,
        state: str = AlertState.FIRING,
    ) -> AlertCheck:
        check = AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=state,
            calculated_value=42.0,
            investigation_status=investigation_status,
            notification_sent_at=notification_sent_at,
            notification_suppressed_by_agent=notification_suppressed_by_agent,
            targets_notified=targets_notified or {},
        )
        # `created_at` is auto_now_add — bypass with an UPDATE so the parametrized
        # ages drive the safety-net's cutoff predicate.
        AlertCheck.objects.filter(id=check.id).update(created_at=NOW - timedelta(minutes=age_minutes))
        check.refresh_from_db()
        return check

    @parameterized.expand(
        [
            # name, age_minutes, investigation_status, expected_dispatched
            # Terminal states (DONE/FAILED) — picked up after 5 min.
            (
                "done_within_terminal_grace_skipped",
                INVESTIGATION_NOTIFY_GRACE_MINUTES - 1,
                InvestigationStatus.DONE,
                False,
            ),
            (
                "done_past_terminal_grace_dispatched",
                INVESTIGATION_NOTIFY_GRACE_MINUTES + 1,
                InvestigationStatus.DONE,
                True,
            ),
            (
                "failed_past_terminal_grace_dispatched",
                INVESTIGATION_NOTIFY_GRACE_MINUTES + 1,
                InvestigationStatus.FAILED,
                True,
            ),
            # Non-terminal states — must wait the longer running grace so we don't
            # race a healthy long-running investigation.
            (
                "running_within_running_grace_skipped",
                INVESTIGATION_RUNNING_GRACE_MINUTES - 1,
                InvestigationStatus.RUNNING,
                False,
            ),
            (
                "running_past_running_grace_dispatched",
                INVESTIGATION_RUNNING_GRACE_MINUTES + 1,
                InvestigationStatus.RUNNING,
                True,
            ),
            (
                "pending_within_running_grace_skipped",
                INVESTIGATION_RUNNING_GRACE_MINUTES - 1,
                InvestigationStatus.PENDING,
                False,
            ),
            (
                "pending_past_running_grace_dispatched",
                INVESTIGATION_RUNNING_GRACE_MINUTES + 1,
                InvestigationStatus.PENDING,
                True,
            ),
            (
                "skipped_status_past_running_grace_dispatched",
                INVESTIGATION_RUNNING_GRACE_MINUTES + 1,
                InvestigationStatus.SKIPPED,
                True,
            ),
            # Investigation never started (status null) — treated as non-terminal.
            ("null_status_within_running_grace_skipped", INVESTIGATION_RUNNING_GRACE_MINUTES - 1, None, False),
            ("null_status_past_running_grace_dispatched", INVESTIGATION_RUNNING_GRACE_MINUTES + 1, None, True),
        ]
    )
    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    @patch("posthog.tasks.alerts.investigation_notifications.record_alert_delivery")
    def test_grace_period_predicate(
        self,
        _name: str,
        age_minutes: int,
        investigation_status: str | None,
        expected_dispatched: bool,
        mock_record: object,
        mock_dispatch: object,
    ) -> None:
        mock_dispatch.return_value = ["test@posthog.com"]  # type: ignore[attr-defined]

        check = self._make_check(age_minutes=age_minutes, investigation_status=investigation_status)
        notified = run_investigation_notification_safety_net()

        check.refresh_from_db()
        if expected_dispatched:
            assert notified == 1
            assert check.notification_sent_at is not None
            mock_dispatch.assert_called_once()  # type: ignore[attr-defined]
        else:
            assert notified == 0
            assert check.notification_sent_at is None
            mock_dispatch.assert_not_called()  # type: ignore[attr-defined]

    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    def test_skips_legacy_delivered_check(self, mock_dispatch: object) -> None:
        # Pre-PR-3 `notify_alert` populated targets_notified without setting
        # notification_sent_at. The safety net must not double-dispatch these.
        self._make_check(
            age_minutes=INVESTIGATION_RUNNING_GRACE_MINUTES + 60,
            investigation_status=None,
            targets_notified={"users": ["legacy@posthog.com"]},
        )
        notified = run_investigation_notification_safety_net()
        assert notified == 0
        mock_dispatch.assert_not_called()  # type: ignore[attr-defined]

    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    def test_skips_already_suppressed_check(self, mock_dispatch: object) -> None:
        self._make_check(
            age_minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES + 60,
            investigation_status=InvestigationStatus.DONE,
            notification_suppressed_by_agent=True,
        )
        notified = run_investigation_notification_safety_net()
        assert notified == 0
        mock_dispatch.assert_not_called()  # type: ignore[attr-defined]

    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    def test_skips_already_notified_check(self, mock_dispatch: object) -> None:
        self._make_check(
            age_minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES + 60,
            investigation_status=InvestigationStatus.DONE,
            notification_sent_at=NOW - timedelta(minutes=10),
        )
        notified = run_investigation_notification_safety_net()
        assert notified == 0
        mock_dispatch.assert_not_called()  # type: ignore[attr-defined]

    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    def test_skips_disabled_alert(self, mock_dispatch: object) -> None:
        self.alert.enabled = False
        self.alert.save(update_fields=["enabled"])
        self._make_check(
            age_minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES + 60,
            investigation_status=InvestigationStatus.DONE,
        )
        notified = run_investigation_notification_safety_net()
        assert notified == 0
        mock_dispatch.assert_not_called()  # type: ignore[attr-defined]

    @patch("posthog.tasks.alerts.investigation_notifications.dispatch_alert_notification")
    def test_skips_non_agent_alert(self, mock_dispatch: object) -> None:
        self.alert.investigation_agent_enabled = False
        self.alert.save(update_fields=["investigation_agent_enabled"])
        self._make_check(
            age_minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES + 60,
            investigation_status=InvestigationStatus.DONE,
        )
        notified = run_investigation_notification_safety_net()
        assert notified == 0
        mock_dispatch.assert_not_called()  # type: ignore[attr-defined]
