from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.approvals.backend.models import ChangeRequest, ChangeRequestState, ValidationStatus
from products.approvals.backend.tasks import expire_old_change_requests, validate_pending_change_requests
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest


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

    @parameterized.expand(
        [
            # Approved is revalidated: the apply-time access check sets its mark there, so never
            # revisiting it would latch the mark exactly where it is set.
            ("approved", "approved", 1),
            ("applied", "applied", 0),
            ("rejected", "rejected", 0),
            ("expired", "expired", 0),
            ("failed", "failed", 0),
        ]
    )
    def test_which_states_are_revalidated(self, _name, state, expected_checked):
        self.change_request.state = state
        self.change_request.save()

        result = validate_pending_change_requests()

        self.assertEqual(result["checked_count"], expected_checked)

    @patch("products.approvals.backend.tasks.ChangeRequest.get_action_class")
    def test_rechecks_already_stale_requests(self, mock_get_action):
        # STALE must not be a one-way latch: a request marked stale by a transient
        # resolution miss (e.g. the project-scoping bug) needs to be able to heal
        # back to VALID once it matches its precondition again, since cancel is
        # otherwise the only way out for the requester.
        self.change_request.validation_status = "stale"
        self.change_request.save()

        mock_action = mock_get_action.return_value
        mock_action.prepare_context.return_value = {}
        mock_action.check_staleness.return_value = True

        result = validate_pending_change_requests()

        self.assertEqual(result["checked_count"], 1)
        self.assertEqual(result["stale_count"], 0)

    @patch("products.approvals.backend.tasks.ChangeRequest.get_action_class")
    def test_heals_stale_request_that_no_longer_matches_staleness_check(self, mock_get_action):
        self.change_request.validation_status = "stale"
        self.change_request.validation_errors = {"staleness": "Resource has been modified"}
        self.change_request.save()

        mock_action = mock_get_action.return_value
        mock_action.prepare_context.return_value = {}
        mock_action.check_staleness.return_value = False

        result = validate_pending_change_requests()

        self.assertEqual(result["healed_count"], 1)
        self.change_request.refresh_from_db()
        self.assertEqual(self.change_request.validation_status, "valid")
        self.assertIsNone(self.change_request.validation_errors)

    @patch("products.approvals.backend.tasks.ChangeRequest.get_action_class")
    def test_marks_stale_when_resource_changed(self, mock_get_action):
        mock_action = mock_get_action.return_value
        mock_action.prepare_context.return_value = {}
        mock_action.check_staleness.return_value = True

        result = validate_pending_change_requests()

        self.assertEqual(result["stale_count"], 1)
        self.change_request.refresh_from_db()
        self.assertEqual(self.change_request.validation_status, "stale")
        self.assertIsNotNone(self.change_request.validation_errors)
        self.assertIsNotNone(self.change_request.validated_at)

    @patch("products.approvals.backend.tasks.ChangeRequest.get_action_class")
    def test_leaves_unchanged_when_not_stale(self, mock_get_action):
        mock_action = mock_get_action.return_value
        mock_action.prepare_context.return_value = {}
        mock_action.check_staleness.return_value = False

        result = validate_pending_change_requests()

        self.assertEqual(result["checked_count"], 1)
        self.assertEqual(result["stale_count"], 0)
        self.change_request.refresh_from_db()
        self.assertEqual(self.change_request.validation_status, "valid")


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

    @patch("products.approvals.backend.tasks.send_approval_expired_notification")
    def test_expire_task_sends_notifications(self, mock_notification):
        expire_old_change_requests()

        mock_notification.assert_called_once()
        notified_cr = mock_notification.call_args[0][0]
        self.assertEqual(notified_cr.pk, self.expired_request.pk)


class TestValidationClearsAnInvalidRequestWhenAccessReturns(APILicensedTest):
    # Marking a request invalid is only safe if something clears it. The task derives the status
    # rather than branching per transition, so the invalid-to-valid direction is covered too.

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.flag = FeatureFlag.objects.create(
            team=self.team,
            key="heals",
            name="heals",
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )
        self.change_request = ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(self.flag.id),
            intent={
                "flag_id": self.flag.id,
                "flag_key": self.flag.key,
                "http_method": "PATCH",
                "gated_changes": {"active": True},
                "full_request_data": {"active": True},
                "preconditions": {"version": self.flag.version, "updated_at": None},
            },
            intent_display={"description": "Enable"},
            policy_snapshot={},
            state=ChangeRequestState.PENDING,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def _set_flag_access(self, level: str) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.put(
            "/api/projects/@current/resource_access_controls",
            {"resource": "feature_flag", "access_level": level},
        )
        assert response.status_code == 200, response.content
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def test_invalid_clears_on_an_approved_request_too(self) -> None:
        # The apply-time check only runs once a request is approved, so an approved request is
        # exactly where the invalid mark gets set and must therefore be revisited.
        ChangeRequest.objects.filter(pk=self.change_request.pk).update(state=ChangeRequestState.APPROVED)

        self._set_flag_access("none")
        validate_pending_change_requests()
        self.change_request.refresh_from_db()
        assert self.change_request.validation_status == ValidationStatus.INVALID

        self._set_flag_access("editor")
        validate_pending_change_requests()
        self.change_request.refresh_from_db()
        assert self.change_request.validation_status == ValidationStatus.VALID

    def test_invalid_clears_once_access_returns(self) -> None:
        self._set_flag_access("none")
        validate_pending_change_requests()
        self.change_request.refresh_from_db()
        assert self.change_request.validation_status == ValidationStatus.INVALID

        self._set_flag_access("editor")
        validate_pending_change_requests()
        self.change_request.refresh_from_db()
        assert self.change_request.validation_status == ValidationStatus.VALID
        assert self.change_request.validation_errors is None
