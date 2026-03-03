from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.approvals.exceptions import InvalidStateError
from posthog.approvals.models import ChangeRequest, ChangeRequestState
from posthog.approvals.services import ChangeRequestService


class TestApproveRejectRaceCondition(BaseTest):
    """Verify that state is re-checked inside the select_for_update lock."""

    def setUp(self):
        super().setUp()
        self.change_request = ChangeRequest.objects.create(
            team=self.team,
            organization=self.organization,
            created_by=self.user,
            action_key="feature_flag.enable",
            resource_type="feature_flag",
            state=ChangeRequestState.PENDING,
            intent={"gated_changes": {"active": True}},
            intent_display={"description": "Enable feature flag"},
            policy_snapshot={"quorum": 1, "users": [self.user.id], "allow_self_approve": True},
            expires_at=timezone.now() + timedelta(days=7),
        )

    def _locked_cr_with_state(self, state: str) -> MagicMock:
        locked_qs = MagicMock()
        cr_copy = ChangeRequest.objects.get(pk=self.change_request.pk)
        cr_copy.state = state
        locked_qs.get.return_value = cr_copy
        return locked_qs

    def test_approve_raises_when_state_changed_under_lock(self):
        service = ChangeRequestService(self.change_request, self.user)

        with patch.object(
            ChangeRequest.objects,
            "select_for_update",
            return_value=self._locked_cr_with_state(ChangeRequestState.REJECTED),
        ):
            with self.assertRaises(InvalidStateError):
                service.approve(reason="LGTM")

    def test_reject_raises_when_state_changed_under_lock(self):
        service = ChangeRequestService(self.change_request, self.user)

        with patch.object(
            ChangeRequest.objects,
            "select_for_update",
            return_value=self._locked_cr_with_state(ChangeRequestState.APPLIED),
        ):
            with self.assertRaises(InvalidStateError):
                service.reject(reason="Not ready")
