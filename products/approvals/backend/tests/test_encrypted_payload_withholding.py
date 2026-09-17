from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from products.approvals.backend.models import ApprovalPolicy, ChangeRequest, ChangeRequestState
from products.approvals.backend.services import ChangeRequestService
from products.feature_flags.backend.encrypted_flag_payloads import REDACTED_PAYLOAD_VALUE, flag_payload_codec
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Invented, not taken from anywhere. Long enough that a substring search cannot match by accident.
SECRET_PAYLOAD = '"tok-zzz-invented-placeholder-42"'


@patch("products.approvals.backend.decorators._is_approvals_enabled", return_value=True)
class TestEncryptedPayloadWithholding(APIBaseTest):
    """A gated write reaches the approval gate before the serializer encrypts `filters.payloads`,
    so the plaintext secret used to land in ChangeRequest.intent, in intent_display, and in the
    change_requests API response, which every member with approvals read scope can read. The gate
    must store ciphertext instead, serve the sentinel, and still apply the real payload."""

    def _policy(self, action_key: str) -> ApprovalPolicy:
        return ApprovalPolicy.objects.create(
            organization=self.organization,
            team=self.team,
            action_key=action_key,
            conditions={},
            approver_config={"quorum": 1, "users": [self.user.id]},
            created_by=self.user,
        )

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

    def _gated_enable(self, flag: FeatureFlag, payload: str) -> Any:
        return self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": payload}},
            },
            format="json",
        )

    def test_secret_payload_is_not_stored_or_served_in_plaintext(self, _mock_enabled):
        self._policy("feature_flag.enable")
        flag = self._encrypted_flag()

        response = self._gated_enable(flag, SECRET_PAYLOAD)
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(action_key="feature_flag.enable")
        assert SECRET_PAYLOAD not in str(change_request.intent)
        assert SECRET_PAYLOAD not in str(change_request.intent_display)
        assert change_request.intent["full_request_data"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}

        stored = change_request.intent["encrypted_payloads"]["true"]
        assert flag_payload_codec().decrypt(stored.encode("utf-8")).decode("utf-8") == SECRET_PAYLOAD

        detail = self.client.get(f"/api/projects/{self.team.id}/change_requests/{change_request.id}/")
        assert detail.status_code == 200
        body = detail.content.decode()
        assert SECRET_PAYLOAD not in body
        assert stored not in body, "withheld ciphertext has no reason to leave the API either"

    def test_approving_applies_the_real_payload(self, _mock_enabled):
        self._policy("feature_flag.enable")
        flag = self._encrypted_flag()

        response = self._gated_enable(flag, SECRET_PAYLOAD)
        change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])

        ChangeRequestService(change_request, self.user).approve()

        flag.refresh_from_db()
        assert flag.active is True
        applied = flag.filters["payloads"]["true"]
        # Decrypting once proves the ciphertext was not encrypted a second time on replay.
        assert flag_payload_codec().decrypt(applied.encode("utf-8")).decode("utf-8") == SECRET_PAYLOAD

    # A boolean flag can hold a second payload key while `cross_field.payload_key_not_true` is
    # unenforced, which is the default outside tests.
    @override_settings(FEATURE_FLAG_FILTERS_ENFORCED_RULES=set())
    def test_approving_keeps_an_unchanged_payload_key_readable(self, _mock_enabled):
        self._policy("feature_flag.enable")
        codec = flag_payload_codec()
        flag = self._encrypted_flag()
        flag.filters = {
            **flag.filters,
            "payloads": {**flag.filters["payloads"], "legacy": codec.encrypt(b'"kept"').decode("utf-8")},
        }
        flag.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "has_encrypted_payloads": True,
                "is_remote_configuration": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    # The client changed one payload and echoed the sentinel for the other.
                    "payloads": {"true": SECRET_PAYLOAD, "legacy": REDACTED_PAYLOAD_VALUE},
                },
            },
            format="json",
        )
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(id=response.json()["change_request_id"])
        ChangeRequestService(change_request, self.user).approve()

        flag.refresh_from_db()
        payloads = flag.filters["payloads"]
        assert codec.decrypt(payloads["true"].encode("utf-8")).decode("utf-8") == SECRET_PAYLOAD
        # The sentinel must not land here: it decrypts to nothing, and one bad value fails the
        # decrypt path for the whole map.
        assert codec.decrypt(payloads["legacy"].encode("utf-8")).decode("utf-8") == '"kept"'

    def test_ordinary_payload_stays_visible_to_approvers(self, _mock_enabled):
        self._policy("feature_flag.enable")
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="plain-config",
            active=False,
            created_by=self.user,
            is_remote_configuration=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": '"visible"'}},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "is_remote_configuration": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"visible"'},
                },
            },
            format="json",
        )
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(action_key="feature_flag.enable")
        detail = self.client.get(f"/api/projects/{self.team.id}/change_requests/{change_request.id}/")
        assert detail.json()["intent"]["full_request_data"]["filters"]["payloads"] == {"true": '"visible"'}

    def test_legacy_change_request_without_the_marker_is_redacted(self, _mock_enabled):
        # A write from before the gate withheld the payload could store plaintext with no
        # `has_encrypted_payloads` beside it: the field is resolved against the flag inside the
        # serializer body, after the gate has already captured the change. The read path has to
        # ask the flag in that case, or the API keeps serving the secret.
        flag = self._encrypted_flag()
        change_request = ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag.id),
            intent={
                "flag_id": flag.id,
                "flag_key": flag.key,
                "full_request_data": {
                    "active": True,
                    "filters": {
                        "groups": [{"properties": [], "rollout_percentage": 100}],
                        "payloads": {"true": SECRET_PAYLOAD},
                    },
                },
            },
            intent_display={"after": {"filters": {"payloads": {"true": SECRET_PAYLOAD}}}},
            policy_snapshot={},
            state=ChangeRequestState.PENDING,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

        detail = self.client.get(f"/api/projects/{self.team.id}/change_requests/{change_request.id}/")

        assert detail.status_code == 200
        assert SECRET_PAYLOAD not in detail.content.decode()
        body = detail.json()
        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}
        assert body["intent_display"]["after"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}
