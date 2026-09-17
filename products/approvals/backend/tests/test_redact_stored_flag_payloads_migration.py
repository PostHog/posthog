from datetime import timedelta
from importlib import import_module
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.apps import apps as global_apps
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from products.approvals.backend.models import ChangeRequest, ChangeRequestState

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

    def _change_request(self, state: str, payload: str) -> ChangeRequest:
        return ChangeRequest.objects.create(
            action_key="feature_flag.enable",
            team=self.team,
            organization=self.organization,
            resource_type="feature_flag",
            resource_id="1",
            intent={"full_request_data": {"filters": {"payloads": {"true": payload}}}},
            intent_display={"description": "Enable", "after": {"filters": {"payloads": {"true": payload}}}},
            policy_snapshot={},
            state=state,
            created_by=self.user,
            expires_at=timezone.now() + timedelta(days=14),
        )

    def test_pending_row_is_scrubbed_and_failed(self):
        change_request = self._change_request(ChangeRequestState.PENDING, SECRET)

        redact_stored_flag_payloads(global_apps, MagicMock())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert SECRET not in str(change_request.intent_display)
        # A pending row would otherwise apply a payload nobody can see any more.
        assert change_request.state == ChangeRequestState.FAILED
        assert "Submit the change again" in change_request.apply_error

    def test_applied_row_is_scrubbed_but_keeps_its_state(self):
        change_request = self._change_request(ChangeRequestState.APPLIED, SECRET)

        redact_stored_flag_payloads(global_apps, MagicMock())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert change_request.state == ChangeRequestState.APPLIED

    def test_a_row_approved_during_the_run_keeps_its_state(self):
        change_request = self._change_request(ChangeRequestState.PENDING, SECRET)
        real_scrub = _migration._scrub

        def approve_between_the_read_and_the_write(payload):
            ChangeRequest.objects.filter(pk=change_request.pk).update(state=ChangeRequestState.APPLIED)
            return real_scrub(payload)

        with patch.object(_migration, "_scrub", side_effect=approve_between_the_read_and_the_write):
            redact_stored_flag_payloads(global_apps, MagicMock())

        change_request.refresh_from_db()
        assert SECRET not in str(change_request.intent)
        assert SECRET not in str(change_request.intent_display)
        # The change really applied, so telling the user it failed would be the opposite of what happened.
        assert change_request.state == ChangeRequestState.APPLIED
        assert not change_request.apply_error

    def test_rerunning_leaves_an_already_scrubbed_row_alone(self):
        change_request = self._change_request(ChangeRequestState.APPLIED, REDACTED_PAYLOAD_VALUE)
        before = change_request.updated_at

        redact_stored_flag_payloads(global_apps, MagicMock())

        change_request.refresh_from_db()
        assert change_request.updated_at == before
