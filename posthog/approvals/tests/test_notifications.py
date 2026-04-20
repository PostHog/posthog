from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.approvals.models import Approval, ApprovalDecision, ApprovalPolicy, ChangeRequest, ChangeRequestState
from posthog.approvals.notifications import (
    _build_change_request_url,
    _send_approval_email,
    send_approval_applied_notification,
    send_approval_decision_notification,
    send_approval_expired_notification,
    send_approval_requested_notification,
)
from posthog.email import CUSTOMER_IO_TEMPLATE_ID_MAP
from posthog.models.instance_setting import override_instance_config


class TestApprovalNotifications(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.first_name = "Test"
        self.user.save()

        self.approver = self._create_user("approver@posthog.com", first_name="Approver")
        self.approver2 = self._create_user("approver2@posthog.com", first_name="Approver2")

        self.policy = ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flags.update_rollout_percentage",
            approver_config={"users": [self.approver.id, self.approver2.id], "quorum": 1},
            enabled=True,
            expires_after=timedelta(days=14),
        )

        self.change_request = ChangeRequest.objects.create(
            action_key="feature_flags.update_rollout_percentage",
            action_version=1,
            team=self.team,
            organization=self.organization,
            resource_type="FeatureFlag",
            resource_id="123",
            intent={"rollout_percentage": 50},
            intent_display={"description": "Update rollout to 50%"},
            policy_snapshot={"quorum": 1},
            created_by=self.user,
            state=ChangeRequestState.PENDING,
            expires_at=timezone.now() + timedelta(days=14),
        )


class TestCustomerIOTemplateIDs(TestApprovalNotifications):
    def test_all_approval_templates_have_customer_io_ids(self):
        expected_templates = [
            "approval_requested",
            "approval_approved",
            "approval_rejected",
            "approval_expired",
            "approval_applied",
        ]

        for template in expected_templates:
            self.assertIn(template, CUSTOMER_IO_TEMPLATE_ID_MAP)
            self.assertIsNotNone(CUSTOMER_IO_TEMPLATE_ID_MAP[template])


class TestBuildChangeRequestUrl(TestApprovalNotifications):
    def test_builds_correct_url(self):
        with self.settings(SITE_URL="https://app.posthog.com"):
            url = _build_change_request_url(self.change_request)
            expected = f"https://app.posthog.com/project/{self.team.project_id}/approvals/{self.change_request.id}"
            self.assertEqual(url, expected)

    def test_strips_trailing_slash_from_site_url(self):
        with self.settings(SITE_URL="https://app.posthog.com/"):
            url = _build_change_request_url(self.change_request)
            expected = f"https://app.posthog.com/project/{self.team.project_id}/approvals/{self.change_request.id}"
            self.assertEqual(url, expected)


class TestSendApprovalEmail(TestApprovalNotifications):
    @patch("posthog.approvals.notifications.EmailMessage")
    @patch("posthog.approvals.notifications.is_email_available")
    def test_sends_email_when_available(self, mock_is_email_available, mock_email_message):
        mock_is_email_available.return_value = True
        mock_message_instance = MagicMock()
        mock_email_message.return_value = mock_message_instance

        with override_instance_config("EMAIL_HOST", "localhost"):
            _send_approval_email(
                recipient=self.approver,
                template_name="approval_requested",
                subject="Test User needs your sign-off",
                change_request=self.change_request,
                extra_context={"requester_name": "Test User"},
            )

        mock_email_message.assert_called_once()
        call_kwargs = mock_email_message.call_args[1]
        self.assertEqual(call_kwargs["template_name"], "approval_requested")
        self.assertEqual(call_kwargs["subject"], "Test User needs your sign-off")
        self.assertTrue(call_kwargs["use_http"])
        mock_message_instance.add_user_recipient.assert_called_once_with(self.approver)
        mock_message_instance.send.assert_called_once_with(send_async=True)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_skips_when_email_not_available(self, mock_is_email_available):
        mock_is_email_available.return_value = False

        _send_approval_email(
            recipient=self.approver,
            template_name="approval_requested",
            subject="Test",
            change_request=self.change_request,
        )

    def test_subjects_are_privacy_conscious(self):
        subjects = [
            "Test User needs your sign-off",
            "Test User approved your change",
            "Your change request was declined",
            "Your change request timed out",
            "Your change is live! 🎉",
        ]
        for subject in subjects:
            self.assertNotIn("feature flag", subject.lower())
            self.assertNotIn("rollout", subject.lower())


class TestSendApprovalRequestedNotification(TestApprovalNotifications):
    @patch("posthog.approvals.notifications._send_approval_email")
    def test_sends_to_all_approvers(self, mock_send_email):
        send_approval_requested_notification(self.change_request)

        self.assertEqual(mock_send_email.call_count, 2)

        call_args_list = [call[1] for call in mock_send_email.call_args_list]
        recipients = [args["recipient"] for args in call_args_list]
        self.assertIn(self.approver, recipients)
        self.assertIn(self.approver2, recipients)

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_skips_when_no_policy(self, mock_send_email):
        self.policy.delete()

        send_approval_requested_notification(self.change_request)

        mock_send_email.assert_not_called()

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_uses_correct_template(self, mock_send_email):
        send_approval_requested_notification(self.change_request)

        call_kwargs = mock_send_email.call_args_list[0][1]
        self.assertEqual(call_kwargs["template_name"], "approval_requested")
        self.assertIn("needs your sign-off", call_kwargs["subject"])

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_continues_on_individual_email_failure(self, mock_send_email):
        mock_send_email.side_effect = [Exception("Email failed"), None]

        send_approval_requested_notification(self.change_request)

        self.assertEqual(mock_send_email.call_count, 2)


class TestSendApprovalDecisionNotification(TestApprovalNotifications):
    @patch("posthog.approvals.notifications._send_approval_email")
    def test_sends_approval_notification(self, mock_send_email):
        approval = Approval.objects.create(
            change_request=self.change_request,
            created_by=self.approver,
            decision=ApprovalDecision.APPROVED,
            reason="Looks good",
        )

        send_approval_decision_notification(self.change_request, approval)

        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["recipient"], self.user)
        self.assertEqual(call_kwargs["template_name"], "approval_approved")
        self.assertIn("approved your change", call_kwargs["subject"])

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_sends_rejection_notification(self, mock_send_email):
        approval = Approval.objects.create(
            change_request=self.change_request,
            created_by=self.approver,
            decision=ApprovalDecision.REJECTED,
            reason="Not safe",
        )

        send_approval_decision_notification(self.change_request, approval)

        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["template_name"], "approval_rejected")
        self.assertEqual(call_kwargs["subject"], "Your change request was declined")

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_skips_when_no_requester(self, mock_send_email):
        self.change_request.created_by = None
        self.change_request.save()

        approval = Approval.objects.create(
            change_request=self.change_request,
            created_by=self.approver,
            decision=ApprovalDecision.APPROVED,
        )

        send_approval_decision_notification(self.change_request, approval)

        mock_send_email.assert_not_called()


class TestSendApprovalExpiredNotification(TestApprovalNotifications):
    @patch("posthog.approvals.notifications._send_approval_email")
    def test_sends_expired_notification(self, mock_send_email):
        send_approval_expired_notification(self.change_request)

        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["recipient"], self.user)
        self.assertEqual(call_kwargs["template_name"], "approval_expired")
        self.assertEqual(call_kwargs["subject"], "Your change request timed out")

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_skips_when_no_requester(self, mock_send_email):
        self.change_request.created_by = None
        self.change_request.save()

        send_approval_expired_notification(self.change_request)

        mock_send_email.assert_not_called()


class TestSendApprovalAppliedNotification(TestApprovalNotifications):
    @patch("posthog.approvals.notifications._send_approval_email")
    def test_sends_applied_notification(self, mock_send_email):
        send_approval_applied_notification(self.change_request)

        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["recipient"], self.user)
        self.assertEqual(call_kwargs["template_name"], "approval_applied")
        self.assertEqual(call_kwargs["subject"], "Your change is live! 🎉")

    @patch("posthog.approvals.notifications._send_approval_email")
    def test_skips_when_no_requester(self, mock_send_email):
        self.change_request.created_by = None
        self.change_request.save()

        send_approval_applied_notification(self.change_request)

        mock_send_email.assert_not_called()


class TestEmailTemplateRendering(TestApprovalNotifications):
    @patch("posthog.approvals.notifications.is_email_available")
    def test_approval_requested_template_renders(self, mock_is_email_available):
        mock_is_email_available.return_value = True

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            message = EmailMessage(
                campaign_key="test_approval_requested",
                template_name="approval_requested",
                subject="Test User needs your sign-off",
                template_context={
                    "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                    "team_name": "Test Team",
                    "requester_name": "Test User",
                },
            )

            self.assertIn("needs your sign-off", message.html_body)
            self.assertIn("Test Team", message.html_body)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_approval_approved_template_renders(self, mock_is_email_available):
        mock_is_email_available.return_value = True

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            message = EmailMessage(
                campaign_key="test_approval_approved",
                template_name="approval_approved",
                subject="Admin User approved your change",
                template_context={
                    "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                    "team_name": "Test Team",
                    "approver_name": "Admin User",
                },
            )

            self.assertIn("approved your change", message.html_body)
            self.assertIn("Test Team", message.html_body)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_approval_rejected_template_renders(self, mock_is_email_available):
        mock_is_email_available.return_value = True

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            message = EmailMessage(
                campaign_key="test_approval_rejected",
                template_name="approval_rejected",
                subject="Your change request was declined",
                template_context={
                    "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                    "team_name": "Test Team",
                    "approver_name": "Admin User",
                },
            )

            self.assertIn("wasn't approved", message.html_body)
            self.assertIn("Test Team", message.html_body)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_approval_expired_template_renders(self, mock_is_email_available):
        mock_is_email_available.return_value = True

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            message = EmailMessage(
                campaign_key="test_approval_expired",
                template_name="approval_expired",
                subject="Your change request timed out",
                template_context={
                    "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                    "team_name": "Test Team",
                },
            )

            self.assertIn("expired", message.html_body)
            self.assertIn("Test Team", message.html_body)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_approval_applied_template_renders(self, mock_is_email_available):
        mock_is_email_available.return_value = True

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            message = EmailMessage(
                campaign_key="test_approval_applied",
                template_name="approval_applied",
                subject="Your change is live! 🎉",
                template_context={
                    "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                    "team_name": "Test Team",
                },
            )

            self.assertIn("is live", message.html_body)
            self.assertIn("Test Team", message.html_body)

    @patch("posthog.approvals.notifications.is_email_available")
    def test_templates_contain_cta_button(self, mock_is_email_available):
        mock_is_email_available.return_value = True
        templates_with_cta = {
            "approval_requested": "Review changes",
            "approval_approved": "View details",
            "approval_rejected": "See feedback",
            "approval_expired": "View expired request",
            "approval_applied": "View details",
        }

        with override_instance_config("EMAIL_HOST", "localhost"), self.settings(SITE_URL="https://app.posthog.com"):
            from posthog.email import EmailMessage

            for template_name, expected_cta in templates_with_cta.items():
                message = EmailMessage(
                    campaign_key=f"test_{template_name}",
                    template_name=template_name,
                    subject="Test Subject",
                    template_context={
                        "change_request_url": "https://app.posthog.com/project/1/approvals/123",
                        "team_name": "Test Team",
                        "requester_name": "Test User",
                        "approver_name": "Admin User",
                    },
                )
                self.assertIn(
                    expected_cta, message.html_body, f"Template {template_name} should have CTA button '{expected_cta}'"
                )
