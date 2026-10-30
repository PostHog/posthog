from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models import Organization, User
from posthog.temporal.ai_observability.eval_reports.auto_disable import disable_undeliverable_report

from products.ai_observability.backend.models.evaluation_reports import EvaluationReport
from products.ai_observability.backend.models.evaluations import Evaluation


@patch("posthog.email.is_email_available", return_value=True)
@patch("posthog.email.EmailMessage")
@patch("products.notifications.backend.facade.api.create_notification")
class TestDisableUndeliverableReport(BaseTest):
    def _create_report(self, created_by: User | None) -> EvaluationReport:
        evaluation = Evaluation.objects.create(
            team=self.team,
            name="Test\nEval",
            evaluation_type="llm_judge",
            evaluation_config={"prompt": "test prompt"},
            output_type="boolean",
            output_config={},
            enabled=True,
            created_by=self.user,
            conditions=[{"id": "c1", "rollout_percentage": 100, "properties": []}],
        )
        return EvaluationReport.objects.create(
            team=self.team,
            evaluation=evaluation,
            frequency=EvaluationReport.Frequency.SCHEDULED,
            rrule="FREQ=DAILY",
            starts_at=timezone.now(),
            delivery_targets=[{"type": "slack", "integration_id": 1, "channel": "C0123|#reports"}],
            created_by=created_by,
        )

    def _make_report_run(self) -> MagicMock:
        return MagicMock(pk="run-id", delivery_errors=["Failed to send Slack message to #reports: Invite it."])

    @parameterized.expand([("report_creator", True), ("evaluation_creator_of_default_report", False)])
    def test_disables_once_and_notifies_owner(
        self, mock_create_notification, mock_email_message, _mock_available, _name, report_has_creator
    ):
        report = self._create_report(created_by=self.user if report_has_creator else None)

        disable_undeliverable_report(report, self._make_report_run())
        disable_undeliverable_report(EvaluationReport.objects.get(pk=report.pk), self._make_report_run())

        report.refresh_from_db()
        self.assertFalse(report.enabled)
        mock_create_notification.assert_called_once()
        self.assertEqual(mock_create_notification.call_args.args[0].target_id, str(self.user.id))
        mock_email_message.return_value.add_user_recipient.assert_called_once_with(self.user)
        mock_email_message.return_value.send.assert_called_once()
        self.assertNotIn("\n", mock_email_message.call_args.kwargs["subject"])

    def test_report_with_changed_targets_stays_enabled(
        self, mock_create_notification, mock_email_message, _mock_available
    ):
        report = self._create_report(created_by=self.user)
        EvaluationReport.objects.filter(pk=report.pk).update(
            delivery_targets=[{"type": "slack", "integration_id": 1, "channel": "C0456|#fixed"}]
        )

        disable_undeliverable_report(report, self._make_report_run())

        report.refresh_from_db()
        self.assertTrue(report.enabled)
        mock_create_notification.assert_not_called()
        mock_email_message.assert_not_called()

    def test_creator_outside_the_project_is_not_notified(
        self, mock_create_notification, mock_email_message, _mock_available
    ):
        other_org = Organization.objects.create(name="Other org")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", "password")
        report = self._create_report(created_by=outsider)

        disable_undeliverable_report(report, self._make_report_run())

        report.refresh_from_db()
        self.assertFalse(report.enabled)
        mock_create_notification.assert_not_called()
        mock_email_message.assert_not_called()
