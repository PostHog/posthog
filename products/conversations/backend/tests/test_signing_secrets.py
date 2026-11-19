from posthog.test.base import BaseTest

from posthog.models import ActivityLog

from products.conversations.backend.models import SigningSecret
from products.conversations.backend.services.signing_secrets import retire_leaked_signing_secret


class TestRetireLeakedSigningSecret(BaseTest):
    def _changes(self):
        entry = (
            ActivityLog.objects.filter(team_id=self.team.id, scope="Team", item_id=str(self.team.id))
            .order_by("-created_at")
            .first()
        )
        return [change["field"] for change in entry.detail["changes"]] if entry else []

    def test_replaces_active_secret_and_logs_the_change(self):
        row = SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_leaked")

        self.assertTrue(retire_leaked_signing_secret(self.team.id, "phs_leaked"))

        row.refresh_from_db()
        self.assertNotEqual(row.secret, "phs_leaked")
        self.assertTrue(row.rotated_independently)
        self.assertIn("conversations_signing_secret", self._changes())

    def test_clears_a_previous_secret_holding_the_token(self):
        from django.utils import timezone

        row = SigningSecret.objects.for_team(self.team.id).create(
            team=self.team,
            secret="phs_rotated_fresh",
            previous_secret="phs_leaked",
            previous_secret_rotated_at=timezone.now(),
            rotated_independently=True,
        )

        # The active secret stays, so nothing was "replaced" for the exposure email.
        self.assertFalse(retire_leaked_signing_secret(self.team.id, "phs_leaked"))

        row.refresh_from_db()
        self.assertEqual(row.secret, "phs_rotated_fresh")
        self.assertIsNone(row.previous_secret)
        self.assertIsNone(row.previous_secret_rotated_at)
        self.assertIn("conversations_signing_secret_previous", self._changes())

    def test_leaves_an_unrelated_row_untouched(self):
        row = SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_unrelated")

        self.assertFalse(retire_leaked_signing_secret(self.team.id, "phs_leaked"))

        row.refresh_from_db()
        self.assertEqual(row.secret, "phs_unrelated")
        self.assertFalse(row.rotated_independently)
        self.assertEqual(self._changes(), [])
