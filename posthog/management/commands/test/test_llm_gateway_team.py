from datetime import UTC, datetime
from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError


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

    def test_enable_is_idempotent(self) -> None:
        # Pre-enable the team; second call must be a no-op and not overwrite the timestamp.
        self.team.llm_gateway_enabled_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        out = self._run("enable", str(self.team.id))
        self.team.refresh_from_db()
        self.assertEqual(self.team.llm_gateway_enabled_at, datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
        self.assertIn("no-op", out)

    def test_revoke_sets_revoked_at(self) -> None:
        out = self._run("revoke", str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNotNone(self.team.llm_gateway_revoked_at)
        self.assertIn("revoke ok", out)

    def test_revoke_is_idempotent(self) -> None:
        self.team.llm_gateway_revoked_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        out = self._run("revoke", str(self.team.id))
        self.team.refresh_from_db()
        self.assertEqual(self.team.llm_gateway_revoked_at, datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC))
        self.assertIn("no-op", out)

    def test_unrevoke_clears_revoked_at(self) -> None:
        self.team.llm_gateway_revoked_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        out = self._run("unrevoke", str(self.team.id))
        self.team.refresh_from_db()
        self.assertIsNone(self.team.llm_gateway_revoked_at)
        self.assertIn("unrevoke ok", out)

    def test_unrevoke_on_already_active_is_noop(self) -> None:
        self.assertIsNone(self.team.llm_gateway_revoked_at)
        out = self._run("unrevoke", str(self.team.id))
        self.assertIn("no-op", out)

    def test_status_admit_when_enabled_and_not_revoked(self) -> None:
        self.team.llm_gateway_enabled_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        out = self._run("status", str(self.team.id))
        self.assertIn("state=admit", out)

    def test_status_deny_when_unenrolled(self) -> None:
        out = self._run("status", str(self.team.id))
        self.assertIn("state=deny", out)

    def test_status_deny_when_revoked(self) -> None:
        self.team.llm_gateway_enabled_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
        self.team.llm_gateway_revoked_at = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
        self.team.save()
        out = self._run("status", str(self.team.id))
        self.assertIn("state=deny", out)

    def test_unknown_team_id_raises(self) -> None:
        with self.assertRaises(CommandError):
            self._run("enable", "999999999")

    def test_unknown_api_token_raises(self) -> None:
        with self.assertRaises(CommandError):
            self._run("enable", "phc_does_not_exist")

    def test_garbage_team_arg_raises(self) -> None:
        with self.assertRaises(CommandError):
            self._run("enable", "not-an-id-or-token")
