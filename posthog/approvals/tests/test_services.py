from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.approvals.exceptions import ApplyFailed, InvalidStateError
from posthog.approvals.models import ChangeRequest, ChangeRequestState
from posthog.approvals.services import ChangeRequestService, apply_change_request


class TestApproveRejectRaceCondition(BaseTest):
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

    @parameterized.expand(
        [
            ("approve", ChangeRequestState.REJECTED, "LGTM"),
            ("reject", ChangeRequestState.APPLIED, "Not ready"),
        ]
    )
    def test_raises_when_state_changed_under_lock(self, method_name, locked_state, reason):
        service = ChangeRequestService(self.change_request, self.user)

        with patch.object(
            ChangeRequest.objects,
            "select_for_update",
            return_value=self._locked_cr_with_state(locked_state),
        ):
            with self.assertRaises(InvalidStateError):
                getattr(service, method_name)(reason=reason)


class TestApplyChangeRequestValidation(BaseTest):
    def test_raises_apply_failed_when_validation_fails(self):
        change_request = ChangeRequest.objects.create(
            team=self.team,
            organization=self.organization,
            created_by=self.user,
            action_key="feature_flag.enable",
            resource_type="feature_flag",
            state=ChangeRequestState.APPROVED,
            intent={"gated_changes": {"active": True}},
            intent_display={"description": "Enable feature flag"},
            policy_snapshot={"quorum": 1, "users": [self.user.id]},
            expires_at=timezone.now() + timedelta(days=7),
        )

        mock_action = MagicMock()
        mock_action.prepare_context.return_value = {}
        mock_action.validate_intent.return_value = (False, {"active": ["Invalid value"]})

        with patch("posthog.approvals.services.get_action", return_value=mock_action):
            with self.assertRaises(ApplyFailed):
                apply_change_request(change_request)
