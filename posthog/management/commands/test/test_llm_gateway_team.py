from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models.team.team import Team


class TestLLMGatewayTeamCommand(BaseTest):
    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("llm_gateway_team", *args, stdout=out)
        return out.getvalue()

    def test_enable_by_team_id(self) -> None:
        self.assertIsNone(self.team.llm_gateway_enabled_at)
        out = self._run("enable", str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.llm_gateway_enabled_at)
        self.assertIn("enable ok", out)

    def test_enable_by_api_token(self) -> None:
        out = self._run("enable", self.team.api_token)
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.llm_gateway_enabled_at)
        self.assertIn(self.team.api_token, out)

    @parameterized.expand([("enable", "llm_gateway_enabled_at"), ("revoke", "llm_gateway_revoked_at")])
    def test_set_action_is_idempotent(self, action: str, field: str) -> None:
        # Pre-set the field; second call must be a no-op and not overwrite the timestamp.
        original = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        setattr(self.team, field, original)
        self.team.save()
        out = self._run(action, str(self.team.id))
        self.team.refresh_from_db()
        self.assertEqual(getattr(self.team, field), original)
        self.assertIn("no-op", out)

    def test_revoke_sets_revoked_at(self) -> None:
        out = self._run("revoke", str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.llm_gateway_revoked_at)
        self.assertIn("revoke ok", out)

    @parameterized.expand(
        [
            ("unenable", "llm_gateway_enabled_at"),
            ("unrevoke", "llm_gateway_revoked_at"),
        ]
    )
    def test_clear_action_clears_field(self, action: str, field: str) -> None:
        setattr(self.team, field, datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
        self.team.save()
        out = self._run(action, str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNone(getattr(self.team, field))
        self.assertIn(f"{action} ok", out)

    @parameterized.expand(
        [
            ("unenable", "llm_gateway_enabled_at"),
            ("unrevoke", "llm_gateway_revoked_at"),
        ]
    )
    def test_clear_action_on_already_null_is_noop(self, action: str, field: str) -> None:
        self.assertIsNone(getattr(self.team, field))
        out = self._run(action, str(self.team.id))
        self.assertIn("no-op", out)

    @parameterized.expand(
        [
            ("admit_when_enabled_and_not_revoked", datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC), None, "state=admit"),
            ("deny_when_unenrolled", None, None, "state=deny"),
            (
                "deny_when_revoked",
                datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
                datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC),
                "state=deny",
            ),
            ("deny_when_only_revoked_without_enabled", None, datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC), "state=deny"),
        ]
    )
    def test_status(self, _name: str, enabled_at, revoked_at, expected_marker: str) -> None:
        self.team.llm_gateway_enabled_at = enabled_at
        self.team.llm_gateway_revoked_at = revoked_at
        self.team.save()
        out = self._run("status", str(self.team.id))
        self.assertIn(expected_marker, out)

    @parameterized.expand(
        [
            ("unknown_team_id", "999999999"),
            ("unknown_api_token", "phc_does_not_exist"),
            ("garbage_arg", "not-an-id-or-token"),
        ]
    )
    def test_resolve_failure_raises(self, _name: str, arg: str) -> None:
        with self.assertRaises(CommandError):
            self._run("enable", arg)

    @parameterized.expand([("integer", "5", "5.000000"), ("fractional", "0.5", "0.500000"), ("zero", "0", "0.000000")])
    def test_set_allowance_stores_quantized_value(self, _name: str, arg: str, expected: str) -> None:
        out = self._run("set-allowance", str(self.team.id), arg)
        self.team.refresh_from_db()
        self.assertEqual(self.team.llm_gateway_overspend_allowance_usd, Decimal(expected))
        self.assertIn("set-allowance ok", out)

    def test_set_allowance_idempotent(self) -> None:
        self.team.llm_gateway_overspend_allowance_usd = Decimal("5.000000")
        self.team.save()
        out = self._run("set-allowance", str(self.team.id), "5")
        self.assertIn("no-op", out)

    def test_clear_allowance_unsets_value(self) -> None:
        self.team.llm_gateway_overspend_allowance_usd = Decimal("5.000000")
        self.team.save()
        out = self._run("clear-allowance", str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNone(self.team.llm_gateway_overspend_allowance_usd)
        self.assertIn("clear-allowance ok", out)

    def test_clear_allowance_on_unset_is_noop(self) -> None:
        out = self._run("clear-allowance", str(self.team.id))
        self.assertIn("no-op", out)

    @parameterized.expand([("negative", "-1"), ("too_large", "10001"), ("too_precise", "1.0000001"), ("nan", "nan")])
    def test_set_allowance_rejects_invalid(self, _name: str, arg: str) -> None:
        with self.assertRaises(CommandError):
            self._run("set-allowance", str(self.team.id), arg)
        self.team.refresh_from_db()
        self.assertIsNone(self.team.llm_gateway_overspend_allowance_usd)

    def test_set_allowance_rejects_child_environment(self) -> None:
        # Child-env value never reaches the wire (projection reads the root team), so reject.
        child = Team.objects.create(organization=self.organization, name="child env", parent_team=self.team)
        with self.assertRaises(CommandError):
            self._run("set-allowance", str(child.id), "5")
        child.refresh_from_db()
        self.assertIsNone(child.llm_gateway_overspend_allowance_usd)

    def test_refresh_rewrites_cache_without_field_change(self) -> None:
        # refresh exists so an operator can re-warm a drifted cache without
        # toggling enabled_at/revoked_at (which enable/revoke would no-op on).
        self.team.llm_gateway_enabled_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        before_enabled = self.team.llm_gateway_enabled_at
        before_revoked = self.team.llm_gateway_revoked_at
        with patch("posthog.management.commands.llm_gateway_team.update_team_llm_gateway_policy_cache") as mock_update:
            out = self._run("refresh", str(self.team.id))
        self.team.refresh_from_db()
        mock_update.assert_called_once_with(self.team)
        self.assertEqual(self.team.llm_gateway_enabled_at, before_enabled)
        self.assertEqual(self.team.llm_gateway_revoked_at, before_revoked)
        self.assertIn("refresh ok", out)
