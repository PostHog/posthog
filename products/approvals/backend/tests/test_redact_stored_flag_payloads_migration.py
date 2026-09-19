from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps as global_apps
from django.db import connection
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.approvals.backend.models import ChangeRequest, ChangeRequestState
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# The module name starts with a digit, so it cannot be imported with an import statement.
_migration = import_module("products.approvals.backend.migrations.0004_redact_stored_flag_payloads")
REDACTED_PAYLOAD_VALUE = _migration.REDACTED_PAYLOAD_VALUE
_scrub = _migration._scrub
redact_stored_flag_payloads = _migration.redact_stored_flag_payloads

SECRET = '"tok-zzz-invented-placeholder-42"'


class TestScrub(SimpleTestCase):
    @parameterized.expand(
        [
            ("no filters", {"flag_key": "f"}, False),
            ("filters without payloads", {"filters": {"groups": []}}, False),
            ("already redacted", {"filters": {"payloads": {"true": REDACTED_PAYLOAD_VALUE}}}, False),
            ("plaintext payload", {"filters": {"payloads": {"true": SECRET}}}, True),
        ]
    )
    def test_reports_whether_anything_changed(self, _name, payload: dict[str, Any], expected: bool):
        _, changed = _scrub(payload)
        assert changed is expected

    def test_replaces_every_payload_value_at_any_depth(self):
        scrubbed, changed = _scrub(
            {
                "full_request_data": {"filters": {"payloads": {"true": SECRET, "other": SECRET}, "groups": [1]}},
                "after": {"filters": {"payloads": {"true": SECRET}}},
            }
        )

        assert changed is True
        assert SECRET not in str(scrubbed)
        assert scrubbed["full_request_data"]["filters"]["payloads"] == {
            "true": REDACTED_PAYLOAD_VALUE,
            "other": REDACTED_PAYLOAD_VALUE,
        }
        assert scrubbed["after"]["filters"]["payloads"] == {"true": REDACTED_PAYLOAD_VALUE}
        # Sibling keys under `filters` survive the scrub.
        assert scrubbed["full_request_data"]["filters"]["groups"] == [1]


class TestRedactStoredFlagPayloadsMigration(APIBaseTest):
    """Temporary: delete once this migration has applied in every supported environment."""

    def _schema_editor(self) -> SimpleNamespace:
        # The scrub reads the flag table directly, so it needs a real connection rather than a mock.
        return SimpleNamespace(connection=connection)

    def _flag(self, *, encrypted: bool, key: str = "secret-config") -> FeatureFlag:
        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            active=False,
            created_by=self.user,
            has_encrypted_payloads=encrypted,
            is_remote_configuration=encrypted,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

    def _change_request(
        self, state: str, payload: str, *, flag_id: int = 1, marker: bool | None = None
    ) -> ChangeRequest:
        full_request_data: dict[str, Any] = {"filters": {"payloads": {"true": payload}}}
        if marker is not None:
            full_request_data["has_encrypted_payloads"] = marker
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id=str(flag_id),
            intent={"flag_id": flag_id, "full_request_data": full_request_data},
            intent_display={"description": "Enable", "after": {"filters": {"payloads": {"true": payload}}}},
            policy_snapshot={},
            state=state,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=14),
        )

    def test_pending_row_is_scrubbed_and_failed(self):
        flag = self._flag(encrypted=True)
        change_request = self._change_request(ChangeRequestState.PENDING, SECRET, flag_id=flag.id)

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert SECRET not in str(change_request.intent_display)
        # A pending row would otherwise apply a payload nobody can see any more.
        assert change_request.state == ChangeRequestState.FAILED
        assert "Submit the change again" in change_request.apply_error

    def test_applied_row_is_scrubbed_but_keeps_its_state(self):
        flag = self._flag(encrypted=True)
        change_request = self._change_request(ChangeRequestState.APPLIED, SECRET, flag_id=flag.id)

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert change_request.state == ChangeRequestState.APPLIED

    def test_a_row_approved_during_the_run_keeps_its_state(self):
        flag = self._flag(encrypted=True)
        change_request = self._change_request(ChangeRequestState.PENDING, SECRET, flag_id=flag.id)
        real_scrub = _migration._scrub

        def approve_between_the_read_and_the_write(payload):
            ChangeRequest.objects.filter(pk=change_request.pk).update(state=ChangeRequestState.APPLIED)
            return real_scrub(payload)

        with patch.object(_migration, "_scrub", side_effect=approve_between_the_read_and_the_write):
            redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert SECRET not in str(change_request.intent_display)
        # The change really applied, so telling the user it failed would be the opposite of what happened.
        assert change_request.state == ChangeRequestState.APPLIED
        assert not change_request.apply_error

    def test_rerunning_leaves_an_already_scrubbed_row_alone(self):
        flag = self._flag(encrypted=True)
        change_request = self._change_request(ChangeRequestState.APPLIED, REDACTED_PAYLOAD_VALUE, flag_id=flag.id)
        before = change_request.updated_at

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert change_request.updated_at == before

    def test_a_row_for_a_flag_that_does_not_encrypt_payloads_is_left_alone(self):
        # The rollout asks for a second pass once old workers stop, and by then this release has
        # written correct rows whose payloads are readable by design. Clearing one would destroy
        # good data and fail a valid approval with a message saying a secret was removed.
        flag = self._flag(encrypted=False, key="plain-config")
        change_request = self._change_request(ChangeRequestState.PENDING, '"visible"', flag_id=flag.id)

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert change_request.intent["full_request_data"]["filters"]["payloads"] == {"true": '"visible"'}
        assert change_request.state == ChangeRequestState.PENDING
        assert not change_request.apply_error

    def test_the_stored_marker_decides_without_asking_a_flag(self):
        # No flag row exists for this id, so only the marker in the stored change can classify it.
        change_request = self._change_request(ChangeRequestState.PENDING, SECRET, flag_id=9_999_999, marker=True)

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert change_request.state == ChangeRequestState.FAILED

    def test_a_downgrade_keeps_the_plaintext_it_proposes(self):
        # The change turns encryption off, so its payload is the public value it will apply. The
        # flag still reports encrypted until it applies, and the marker has to win.
        flag = self._flag(encrypted=True)
        change_request = self._change_request(ChangeRequestState.PENDING, '"now-public"', flag_id=flag.id, marker=False)

        redact_stored_flag_payloads(global_apps, self._schema_editor())

        change_request.refresh_from_db()
        assert change_request.intent["full_request_data"]["filters"]["payloads"] == {"true": '"now-public"'}
        assert change_request.state == ChangeRequestState.PENDING
