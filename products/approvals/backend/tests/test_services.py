from datetime import timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.approvals.backend.exceptions import ApplyFailed, InvalidStateError, PreconditionFailed
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState, ValidationStatus
from products.approvals.backend.services import ChangeRequestService, apply_change_request
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.encrypted_flag_payloads import (
    REDACTED_PAYLOAD_VALUE,
    FlagPayloadCodec,
    flag_payload_codec,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag

from ee.api.test.base import APILicensedTest


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


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestApplyOnEncryptedPayloadsFlag(APIBaseTest):
    def test_approving_a_change_request_applies_the_flag(self, _mock_enabled):
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key="feature_flag.enable",
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="secret-config",
            active=False,
            created_by=self.user,
            has_encrypted_payloads=True,
            is_remote_configuration=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": flag_payload_codec().encrypt(b'"previous"').decode("utf-8")},
            },
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"next"'},
                },
            },
            format="json",
        )
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        ChangeRequestService(change_request, self.user).approve()

        change_request.refresh_from_db()
        assert change_request.state == ChangeRequestState.APPLIED
        flag.refresh_from_db()
        assert flag.active is True
        stored_payload = flag.filters["payloads"]["true"]
        decrypted_payload = flag_payload_codec().decrypt(stored_payload.encode("utf-8")).decode("utf-8")
        assert decrypted_payload == '"next"', stored_payload


class TestApplyApprovedEncryptedPayloads(APIBaseTest):
    # A change request can carry its flag payload as ciphertext under `encrypted_payloads`, with
    # the replayed change holding only the sentinel. Applying one has to reach the flag, so that a
    # request written in this shape can be approved by any process running this code.

    def _encrypted_flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="secret-config",
            active=False,
            created_by=self.user,
            has_encrypted_payloads=True,
            is_remote_configuration=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "payloads": {"true": flag_payload_codec().encrypt(b'"previous"').decode("utf-8")},
            },
        )

    def _change_request(self, flag: FeatureFlag, encrypted_payloads: dict[str, str]) -> ChangeRequest:
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag.id),
            intent={
                "flag_id": flag.id,
                "flag_key": flag.key,
                "http_method": "PATCH",
                "current_state": {"active": False},
                "gated_changes": {"active": True},
                "full_request_data": {
                    "active": True,
                    "has_encrypted_payloads": True,
                    "is_remote_configuration": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "payloads": {"true": REDACTED_PAYLOAD_VALUE},
                    },
                },
                "encrypted_payloads": encrypted_payloads,
                "preconditions": {"version": flag.version, "updated_at": None},
            },
            intent_display={"description": "Enable"},
            policy_snapshot={},
            state=ChangeRequestState.APPROVED,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_apply_writes_the_carried_ciphertext_to_the_flag(self):
        flag = self._encrypted_flag()
        codec = flag_payload_codec()
        change_request = self._change_request(flag, {"true": codec.encrypt(b'"next"').decode("utf-8")})

        apply_change_request(change_request)

        flag.refresh_from_db()
        assert flag.active is True
        # Decrypting once proves the carried ciphertext was not encrypted a second time, which
        # would leave a payload no SDK can read.
        assert codec.decrypt(flag.filters["payloads"]["true"].encode("utf-8")).decode("utf-8") == '"next"'

    def test_apply_fails_when_the_carried_ciphertext_cannot_be_decrypted(self):
        flag = self._encrypted_flag()
        stored_payload = flag.filters["payloads"]["true"]
        # A token this deployment holds no key for, which is what an operator leaves behind by
        # dropping a fallback key while a change request is still open.
        foreign_codec = FlagPayloadCodec.from_keys("k" * 32, [], require_min_length=False)
        change_request = self._change_request(flag, {"true": foreign_codec.encrypt(b'"unreachable"').decode("utf-8")})

        with self.assertRaises(ApplyFailed):
            apply_change_request(change_request)

        flag.refresh_from_db()
        assert flag.active is False
        assert flag.filters["payloads"]["true"] == stored_payload


class TestApplyRechecksOwnership(APIBaseTest):
    # A change request records which product owned the flag when it was raised. Which policy
    # applies is keyed on that owner, so an apply under a different owner would land a change the
    # current owner's approvers never saw.

    def _flag(self) -> FeatureFlag:
        return FeatureFlag.objects.create(team=self.team, key="gated", name="gated", active=False, created_by=self.user)

    def _change_request(self, flag: FeatureFlag, owner_kind: str | None) -> ChangeRequest:
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag.id),
            owner_kind=owner_kind,
            intent={
                "flag_id": flag.id,
                "flag_key": flag.key,
                "http_method": "PATCH",
                "current_state": {"active": False},
                "gated_changes": {"active": True},
                "full_request_data": {"active": True},
                "preconditions": {"version": flag.version, "updated_at": None},
            },
            intent_display={"description": "Enable"},
            policy_snapshot={},
            state=ChangeRequestState.APPROVED,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    @parameterized.expand(
        [
            ("adopted by an experiment after the request", "unowned", True, False),
            ("released by its experiment after the request", "experiment", False, False),
            ("owner unchanged", "unowned", False, True),
            ("still owned by the same experiment", "experiment", True, True),
            ("never classified", None, True, True),
        ]
    )
    def test_apply_refuses_when_the_owner_changed(
        self, _name: str, recorded: str | None, owned_now: bool, should_apply: bool
    ) -> None:
        flag = self._flag()
        change_request = self._change_request(flag, recorded)
        if owned_now:
            Experiment.objects.create(team=self.team, name="exp", feature_flag=flag)

        if should_apply:
            apply_change_request(change_request)
            flag.refresh_from_db()
            assert flag.active is True
        else:
            with self.assertRaises(PreconditionFailed):
                apply_change_request(change_request)
            flag.refresh_from_db()
            assert flag.active is False
            change_request.refresh_from_db()
            assert change_request.state == ChangeRequestState.FAILED


class TestApplyRechecksRequesterAccess(APILicensedTest):
    # Access is checked when a change request is created, because the viewset's access control
    # runs before the gate. An apply replays the write with no authenticated user, so without a
    # second check an approval lets someone outlive their own permissions.

    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()

    def _change_request(self, flag: FeatureFlag) -> ChangeRequest:
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag.id),
            intent={
                "flag_id": flag.id,
                "flag_key": flag.key,
                "http_method": "PATCH",
                "current_state": {"active": False},
                "gated_changes": {"active": True},
                "full_request_data": {"active": True},
                "preconditions": {"version": flag.version, "updated_at": None},
            },
            intent_display={"description": "Enable"},
            policy_snapshot={},
            state=ChangeRequestState.APPROVED,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def _revoke_flag_access(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        response = self.client.put(
            "/api/projects/@current/resource_access_controls",
            {"resource": "feature_flag", "access_level": "none"},
        )
        assert response.status_code == 200, response.content
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    def _create_change_request(self) -> ChangeRequest:
        # A create carries no flag_id, so nothing resolves as an instance at apply.
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=None,
            intent={
                "flag_id": None,
                "flag_key": "born-active",
                "http_method": "POST",
                "current_state": {"active": False},
                "gated_changes": {"active": True},
                "full_request_data": {"key": "born-active", "name": "born", "active": True},
                "preconditions": {"version": None, "updated_at": None},
            },
            intent_display={"description": "Create"},
            policy_snapshot={},
            state=ChangeRequestState.APPROVED,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def test_apply_refuses_a_create_when_the_requester_lost_access(self) -> None:
        change_request = self._create_change_request()
        self._revoke_flag_access()

        with self.assertRaises(PreconditionFailed):
            apply_change_request(change_request)

        assert not FeatureFlag.objects.filter(team=self.team, key="born-active").exists()
        change_request.refresh_from_db()
        assert change_request.validation_status == ValidationStatus.INVALID

    def test_apply_refuses_when_the_requester_account_is_gone(self) -> None:
        # created_by is SET_NULL, so offboarding the requester empties it. Nobody is left whose
        # access can be checked, and the apply must not treat that as permission.
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="orphaned",
            name="orphaned",
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )
        change_request = self._change_request(flag)
        ChangeRequest.objects.filter(pk=change_request.pk).update(created_by=None)
        change_request.refresh_from_db()

        with self.assertRaises(PreconditionFailed):
            apply_change_request(change_request)

        flag.refresh_from_db()
        assert flag.active is False

    @parameterized.expand([("access kept", False, True), ("access revoked", True, False)])
    def test_apply_requires_the_requester_to_still_have_access(
        self, _name: str, revoke: bool, should_apply: bool
    ) -> None:
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="access-gated",
            name="access-gated",
            active=False,
            filters={"groups": [{"properties": [], "rollout_percentage": 50}]},
            created_by=self.user,
        )
        change_request = self._change_request(flag)
        if revoke:
            self._revoke_flag_access()

        if should_apply:
            apply_change_request(change_request)
            flag.refresh_from_db()
            assert flag.active is True
        else:
            with self.assertRaises(PreconditionFailed):
                apply_change_request(change_request)
            flag.refresh_from_db()
            assert flag.active is False
            change_request.refresh_from_db()
            assert change_request.validation_status == ValidationStatus.INVALID
