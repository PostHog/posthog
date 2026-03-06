from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.approvals.models import ChangeRequest
from posthog.approvals.tasks import expire_old_change_requests, validate_pending_change_requests


class TestValidatePendingChangeRequests(BaseTest):
    def setUp(self):
        super().setUp()
        self.change_request = ChangeRequest.objects.create(
            team=self.team,
            organization=self.organization,
            created_by=self.user,
            action_key="feature_flag.update",
            resource_type="feature_flag",
            state="pending",
            validation_status="valid",
            intent={
                "current_state": {"active": False},
                "gated_changes": {"active": True},
            },
            intent_display={"description": "Enable feature flag"},
            policy_snapshot={"quorum": 1, "users": [self.user.id]},
            expires_at=timezone.now() + timedelta(hours=24),
        )

    def test_validation_skips_non_pending_requests(self):
        self.change_request.state = "approved"
        self.change_request.save()

        result = validate_pending_change_requests()

        self.assertEqual(result["validated_count"], 0)
        self.assertEqual(result["invalidated_count"], 0)


class TestExpireOldChangeRequests(BaseTest):
    def setUp(self):
        super().setUp()
        self.expired_request = ChangeRequest.objects.create(
            team=self.team,
            organization=self.organization,
            created_by=self.user,
            action_key="feature_flag.update",
            resource_type="feature_flag",
            state="pending",
            validation_status="valid",
            intent={"gated_changes": {"active": True}},
            intent_display={"description": "Enable feature flag"},
            policy_snapshot={"quorum": 1, "users": [self.user.id]},
            expires_at=timezone.now() - timedelta(hours=1),
        )

    def test_expire_task_skips_future_requests(self):
        self.expired_request.expires_at = timezone.now() + timedelta(hours=1)
        self.expired_request.save()

        result = expire_old_change_requests()

        self.assertEqual(result["expired_count"], 0)

        self.expired_request.refresh_from_db()
        self.assertEqual(self.expired_request.state, "pending")

    @parameterized.expand(
        [
            ("pending", "expired", 1),
            ("approved", "expired", 1),
            ("applied", "applied", 0),
            ("rejected", "rejected", 0),
            ("expired", "expired", 0),
        ]
    )
    def test_expire_task_state_transitions(self, initial_state, expected_state, expected_count):
        self.expired_request.state = initial_state
        self.expired_request.save()

        result = expire_old_change_requests()

        self.assertEqual(result["expired_count"], expected_count)
        self.expired_request.refresh_from_db()
        self.assertEqual(self.expired_request.state, expected_state)

    @patch("posthog.approvals.tasks.send_approval_expired_notification")
    def test_expire_task_sends_notifications(self, mock_notification):
        expire_old_change_requests()

        mock_notification.assert_called_once()
        notified_cr = mock_notification.call_args[0][0]
        self.assertEqual(notified_cr.pk, self.expired_request.pk)
