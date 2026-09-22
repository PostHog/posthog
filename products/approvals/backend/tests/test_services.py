from datetime import timedelta

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from products.approvals.backend.exceptions import ApplyFailed, InvalidStateError
from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import ChangeRequestService, apply_change_request
from products.feature_flags.backend.encrypted_flag_payloads import (
    REDACTED_PAYLOAD_VALUE,
    FlagPayloadCodec,
    flag_payload_codec,
)
from products.feature_flags.backend.models.feature_flag import FeatureFlag


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
