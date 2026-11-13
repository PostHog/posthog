import json
from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import apply_change_request
from products.feature_flags.backend.encrypted_flag_payloads import flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

SECRET = '"rotated-secret"'


def _encrypt(value: str) -> str:
    return flag_payload_codec().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(token: str) -> str:
    return flag_payload_codec().decrypt(token.encode("utf-8")).decode("utf-8")


class _ApprovalsTestBase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.APPROVALS, "name": AvailableFeature.APPROVALS}
        ]
        self.organization.save()

    def _policy(self, action_key: str) -> None:
        ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

    def _flag(self, *, encrypted: bool, active: bool = True) -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key="remote-config",
            active=active,
            created_by=self.user,
            has_encrypted_payloads=encrypted,
            is_remote_configuration=True,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 50}],
                "payloads": {"true": _encrypt('"previous"') if encrypted else '"previous"'},
            },
        )

    def _served(self, change_request: ChangeRequest) -> list[str]:
        """The change request as the detail and list endpoints serve it."""
        base = f"/api/projects/{self.team.id}/change_requests/"
        detail = self.client.get(f"{base}{change_request.id}/")
        listed = self.client.get(base)
        assert detail.status_code == 200, detail.json()
        assert listed.status_code == 200, listed.json()
        return [
            json.dumps(detail.json()),
            json.dumps([row for row in listed.json()["results"] if row["id"] == str(change_request.id)]),
        ]


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestGatedWritesWithholdEncryptedPayloads(_ApprovalsTestBase):
    @parameterized.expand(
        [
            ("update_on_an_encrypted_flag", "feature_flag.update", True, True, {}),
            ("enable_on_an_encrypted_flag", "feature_flag.enable", True, False, {"active": True}),
            ("update_on_a_plain_flag", "feature_flag.update", False, True, {}),
        ]
    )
    def test_a_gated_write_stores_and_serves_a_secret_payload_only_as_ciphertext(
        self, _mock_enabled, _name: str, action_key: str, encrypted: bool, active: bool, extra: dict[str, Any]
    ) -> None:
        self._policy(action_key)
        flag = self._flag(encrypted=encrypted, active=active)
        body = {
            **extra,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": SECRET}},
        }

        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag.id}/", body, format="json")

        assert response.status_code == 409, response.json()
        change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        stored = json.dumps([change_request.intent, change_request.intent_display])
        served = self._served(change_request)
        assert ("rotated-secret" in stored) is not encrypted
        assert all(("rotated-secret" in text) is not encrypted for text in served)
        assert not any("encrypted_payloads" in text for text in served)

        apply_change_request(change_request)

        flag.refresh_from_db()
        payload = flag.filters["payloads"]["true"]
        assert (_decrypt(payload) if encrypted else payload) == SECRET

    def test_a_gated_create_of_an_encrypted_flag_withholds_its_payload(self, _mock_enabled) -> None:
        self._policy("feature_flag.enable")
        body = {
            "key": "born-encrypted",
            "active": True,
            "has_encrypted_payloads": True,
            "is_remote_configuration": True,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": SECRET}},
        }

        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", body, format="json")

        assert response.status_code == 409, response.json()
        change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        assert "rotated-secret" not in json.dumps([change_request.intent, change_request.intent_display])

        apply_change_request(change_request)

        flag = FeatureFlag.objects.get(team=self.team, key="born-encrypted")
        assert _decrypt(flag.filters["payloads"]["true"]) == SECRET


class TestServingChangeRequestsStoredInTheClear(_ApprovalsTestBase):
    @parameterized.expand(
        [
            ("encrypted_flag", True, "kept", {}, True),
            ("plain_flag", False, "kept", {}, False),
            ("soft_deleted_encrypted_flag", True, "soft_deleted", {}, True),
            ("missing_flag", True, "missing", {}, True),
            ("change_that_turns_encryption_off", True, "kept", {"has_encrypted_payloads": False}, False),
        ]
    )
    def test_a_payload_stored_before_the_fix_is_served_only_when_it_is_not_secret(
        self, _name: str, encrypted: bool, flag_state: str, change_extra: dict[str, Any], hidden: bool
    ) -> None:
        flag = self._flag(encrypted=encrypted, active=False)
        change = {
            "active": True,
            **change_extra,
            "filters": {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": SECRET}},
        }
        change_request = ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag.id),
            intent={"flag_id": flag.id, "flag_key": flag.key, "full_request_data": change},
            intent_display={"description": "Enable", "after": change},
            policy_snapshot={},
            state=ChangeRequestState.PENDING,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )
        stored_intent = change_request.intent
        if flag_state == "soft_deleted":
            FeatureFlag.objects.filter(id=flag.id).update(deleted=True)
        elif flag_state == "missing":
            FeatureFlag.objects_including_soft_deleted.filter(id=flag.id).delete()

        served = self._served(change_request)

        assert all(("rotated-secret" in text) is not hidden for text in served)
        change_request.refresh_from_db()
        assert change_request.intent == stored_intent
