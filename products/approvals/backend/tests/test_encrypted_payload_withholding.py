from datetime import timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from products.approvals.backend.actions.feature_flags import _withhold_encrypted_payloads
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
        served = detail.json()
        assert not self._mentions(served, SECRET_PAYLOAD)
        assert not self._mentions(served, stored), "withheld ciphertext has no reason to leave the API either"

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

    def _markerless_change_request(self, flag_id: int, payloads: dict[str, str] | None = None) -> ChangeRequest:
        """A row shaped like a write from before the gate withheld the payload: a readable
        `filters.payloads` and no `has_encrypted_payloads` beside it."""
        payloads = payloads if payloads is not None else {"true": SECRET_PAYLOAD}
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag_id),
            intent={
                "flag_id": flag_id,
                "full_request_data": {
                    "active": True,
                    "filters": {"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": payloads},
                },
            },
            intent_display={"after": {"filters": {"payloads": payloads}}},
            policy_snapshot={},
            state=ChangeRequestState.PENDING,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=7),
        )

    def _served(self, change_request: ChangeRequest) -> Any:
        detail = self.client.get(f"/api/projects/{self.team.id}/change_requests/{change_request.id}/")
        assert detail.status_code == 200, detail.content
        return detail

    @staticmethod
    def _mentions(body: Any, needle: str) -> bool:
        """Search the parsed response for a value containing `needle`.

        The payload values here carry literal quotes, so JSON escaping means a substring test
        against the raw response text can never match and would assert nothing.
        """
        if isinstance(body, dict):
            return any(TestEncryptedPayloadWithholding._mentions(item, needle) for item in body.values())
        if isinstance(body, list):
            return any(TestEncryptedPayloadWithholding._mentions(item, needle) for item in body)
        return needle in body if isinstance(body, str) else False

    def _served_payload_values(self, change_request: ChangeRequest) -> list[str]:
        """Every `filters.payloads` value the API serves, across both response fields."""
        body = self._served(change_request).json()
        found: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                filters = value.get("filters")
                if isinstance(filters, dict) and isinstance(filters.get("payloads"), dict):
                    found.extend(filters["payloads"].values())
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(body["intent"])
        walk(body["intent_display"])
        return found

    def test_legacy_change_request_without_the_marker_is_redacted(self, _mock_enabled):
        # A write from before the gate withheld the payload could store plaintext with no
        # `has_encrypted_payloads` beside it: the field is resolved against the flag inside the
        # serializer body, after the gate has already captured the change. The read path has to
        # ask the flag in that case, or the API keeps serving the secret.
        change_request = self._markerless_change_request(self._encrypted_flag().id)

        detail = self._served(change_request)

        body = detail.json()
        assert not self._mentions(body, SECRET_PAYLOAD)
        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}
        assert body["intent_display"]["after"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}

    def test_a_markerless_row_stays_redacted_after_its_flag_is_soft_deleted(self, _mock_enabled):
        # Flag deletion is soft, and the default manager hides those rows. Resolving the marker
        # through it would report "not encrypted" and hand the secret back.
        flag = self._encrypted_flag()
        change_request = self._markerless_change_request(flag.id)
        flag.deleted = True
        flag.save()

        assert self._served_payload_values(change_request) == [REDACTED_PAYLOAD_VALUE, REDACTED_PAYLOAD_VALUE]

    def test_a_markerless_row_is_redacted_when_its_flag_is_gone(self, _mock_enabled):
        # Nothing is left to say whether the payload was a secret, so redaction is the safe
        # direction: a hard-deleted flag must not turn a withheld payload back into a readable one.
        change_request = self._markerless_change_request(9_999_999)

        body = self._served(change_request).json()

        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}

    def test_a_gated_downgrade_shows_the_plaintext_it_will_apply(self, _mock_enabled):
        # Turning payload encryption off is a supported write. The flag still reports encrypted
        # until the change applies, so asking it would replace the proposed public value with the
        # sentinel and leave the approver consenting to something the screen never showed.
        self._policy("feature_flag.enable")
        flag = self._encrypted_flag()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "has_encrypted_payloads": False,
                "is_remote_configuration": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"now-public"'},
                },
            },
            format="json",
        )
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(action_key="feature_flag.enable")
        body = self._served(change_request).json()

        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {"true": '"now-public"'}

    def test_a_payload_key_named_like_the_sidecar_survives(self, _mock_enabled):
        # The withheld ciphertext is stored under `encrypted_payloads` at the intent root. A flag
        # payload variant may legally carry that same name, and dropping it everywhere would hide
        # a value the approve path still applies.
        ordinary_flag = FeatureFlag.objects.create(
            team=self.team,
            key="plain-variants",
            active=False,
            created_by=self.user,
            is_remote_configuration=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        change_request = self._markerless_change_request(
            ordinary_flag.id, payloads={"encrypted_payloads": '"visible"', "true": '"also-visible"'}
        )

        body = self._served(change_request).json()

        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {
            "encrypted_payloads": '"visible"',
            "true": '"also-visible"',
        }

    def test_a_flag_with_a_null_marker_keeps_an_ordinary_payload_visible(self, _mock_enabled):
        # `has_encrypted_payloads` is nullable, and every other reader treats NULL as false.
        # Resolving a NULL the same way a missing row is resolved would hide a payload that was
        # never a secret, leaving the approver nothing to review.
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="null-marker",
            active=False,
            created_by=self.user,
            is_remote_configuration=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )
        FeatureFlag.objects.filter(id=flag.id).update(has_encrypted_payloads=None)
        change_request = self._markerless_change_request(flag.id, payloads={"true": '"visible"'})

        assert self._served_payload_values(change_request) == ['"visible"', '"visible"']

    def test_a_recorded_answer_survives_the_flag_changing_later(self, _mock_enabled):
        # The gate records whether these payloads were secret when it captured the change. Asking
        # the flag at read time instead would follow it: upgrading a flag to encrypted afterwards
        # would hide a payload that was public when it was approved.
        self._policy("feature_flag.enable")
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="public-then-secret",
            active=False,
            created_by=self.user,
            is_remote_configuration=True,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}], "payloads": {"true": '"public"'}},
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {
                "active": True,
                "filters": {
                    "groups": [{"properties": [], "rollout_percentage": 100}],
                    "payloads": {"true": '"public"'},
                },
            },
            format="json",
        )
        assert response.status_code == 409, response.content

        change_request = ChangeRequest.objects.get(action_key="feature_flag.enable")
        assert change_request.intent["payloads_were_encrypted"] is False

        FeatureFlag.objects.filter(id=flag.id).update(has_encrypted_payloads=True)

        body = self._served(change_request).json()
        assert body["intent"]["full_request_data"]["filters"]["payloads"] == {"true": '"public"'}

    def test_listing_asks_each_flag_once(self, _mock_enabled):
        # `intent` and `intent_display` both carry the payload, so redacting them independently
        # asked the same flag twice per row — two round trips per listed change request.
        flag = self._encrypted_flag()
        self._markerless_change_request(flag.id)
        self._markerless_change_request(flag.id)

        with patch(
            "products.approvals.backend.actions.feature_flags._flag_keeps_payloads_encrypted",
            return_value=True,
        ) as lookup:
            listed = self.client.get(f"/api/projects/{self.team.id}/change_requests/")

        assert listed.status_code == 200, listed.content
        assert len(listed.json()["results"]) == 2
        assert lookup.call_count == 2, "one lookup per change request, not one per response field"


class TestWithholdEncryptedPayloads(SimpleTestCase):
    """The sentinel stands in for a payload the client could not read, so it means something only
    where the flag already holds ciphertext for that key. Treating it as ciphertext anywhere else
    would save a payload map that cannot be decrypted, and one bad entry fails them all.

    Filters validation refuses a new non-`true` payload key on a boolean flag, so the API cannot
    currently build this input end to end. The helper still has to be right: the create path has
    no stored ciphertext for any key, and nothing stops a future caller shape from reaching it.
    """

    @staticmethod
    def _flag(stored: dict[str, str] | None, *, encrypted: bool = True) -> FeatureFlag:
        # Unsaved on purpose: the helper reads only these two attributes, so this needs no database.
        return FeatureFlag(
            has_encrypted_payloads=encrypted,
            filters={"payloads": stored} if stored is not None else {},
        )

    def _withhold(self, payloads: dict[str, str], stored: dict[str, str] | None) -> tuple[Any, Any, Any]:
        change = {"has_encrypted_payloads": True, "filters": {"payloads": payloads}}
        return _withhold_encrypted_payloads(change, self._flag(stored))

    def test_a_sentinel_for_an_unstored_key_is_withheld_like_any_other_value(self):
        codec = flag_payload_codec()
        replayable, encrypted, recorded = self._withhold(
            {"true": SECRET_PAYLOAD, "legacy": REDACTED_PAYLOAD_VALUE},
            stored={"true": codec.encrypt(b'"old"').decode("utf-8")},
        )

        assert recorded is True
        assert set(encrypted) == {"true", "legacy"}
        assert codec.decrypt(encrypted["legacy"].encode("utf-8")).decode("utf-8") == REDACTED_PAYLOAD_VALUE
        assert replayable["filters"]["payloads"] == {
            "true": REDACTED_PAYLOAD_VALUE,
            "legacy": REDACTED_PAYLOAD_VALUE,
        }

    def test_a_sentinel_for_a_stored_key_is_left_for_the_serializer_to_restore(self):
        codec = flag_payload_codec()
        _, encrypted, recorded = self._withhold(
            {"legacy": REDACTED_PAYLOAD_VALUE},
            stored={"legacy": codec.encrypt(b'"kept"').decode("utf-8")},
        )

        assert recorded is True
        assert encrypted == {}, "the stored ciphertext is restored on save, so nothing is withheld"

    def test_a_create_withholds_every_payload(self):
        codec = flag_payload_codec()
        change = {"has_encrypted_payloads": True, "filters": {"payloads": {"true": REDACTED_PAYLOAD_VALUE}}}

        _, encrypted, recorded = _withhold_encrypted_payloads(change, None)

        assert recorded is True
        assert codec.decrypt(encrypted["true"].encode("utf-8")).decode("utf-8") == REDACTED_PAYLOAD_VALUE

    def test_an_unencrypted_change_records_that_its_payloads_were_not_secret(self):
        change = {"filters": {"payloads": {"true": '"public"'}}}

        replayable, encrypted, recorded = _withhold_encrypted_payloads(change, self._flag(None, encrypted=False))

        assert recorded is False
        assert encrypted == {}
        assert replayable is change, "an unencrypted change is stored exactly as it arrived"

    def test_a_change_with_no_payloads_records_nothing(self):
        _, _, recorded = _withhold_encrypted_payloads({"active": True}, self._flag(None))

        assert recorded is None
