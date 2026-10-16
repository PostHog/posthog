from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from products.approvals.backend.exceptions import ApprovalRequired
from products.approvals.backend.models import ChangeRequest, ChangeRequestState
from products.approvals.backend.transactions import gated_atomic, restore_rolled_back_change_request


class TestGatedAtomic(APIBaseTest):
    def _build_pending_change_request(self, resource_id: str = "1") -> ChangeRequest:
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            action_version=1,
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=resource_id,
            intent={},
            intent_display={},
            policy_snapshot={},
            created_by=self.user,
            state=ChangeRequestState.PENDING,
            expires_at=timezone.now() + timedelta(days=1),
        )

    def _raise_approval_required(self) -> None:
        raise ApprovalRequired(
            change_request=self._build_pending_change_request(resource_id="gated"),
            message="Approval required",
            required_approvers={},
        )

    def test_the_gates_change_request_survives_while_the_blocks_other_writes_roll_back(self):
        with patch("products.approvals.backend.transactions.send_approval_requested_notification") as notify:
            with self.assertRaises(ApprovalRequired) as caught:
                with gated_atomic():
                    self._build_pending_change_request(resource_id="copied-alongside")
                    self._raise_approval_required()

        restored = ChangeRequest.objects.get(pk=caught.exception.change_request.id)
        assert restored.resource_id == "gated"
        assert restored.state == ChangeRequestState.PENDING
        assert not ChangeRequest.objects.filter(resource_id="copied-alongside").exists()
        notify.assert_called_once_with(caught.exception.change_request)

    def test_a_block_that_does_not_raise_commits_normally(self):
        with gated_atomic():
            change_request = self._build_pending_change_request()

        assert ChangeRequest.objects.filter(pk=change_request.pk).exists()

    def test_restoring_a_change_request_that_was_never_rolled_back_is_a_no_op(self):
        change_request = self._build_pending_change_request()

        with patch("products.approvals.backend.transactions.send_approval_requested_notification") as notify:
            restore_rolled_back_change_request(change_request)

        assert ChangeRequest.objects.filter(pk=change_request.pk).count() == 1
        notify.assert_not_called()
