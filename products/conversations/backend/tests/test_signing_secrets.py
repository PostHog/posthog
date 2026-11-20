from posthog.test.base import BaseTest

from posthog.models import ActivityLog
from posthog.models.utils import mask_key_value

from products.conversations.backend.models import SigningSecret
from products.conversations.backend.services.signing_secrets import retire_leaked_signing_secret


class TestRetireLeakedSigningSecret(BaseTest):
    def _changes(self):
        entry = (
            ActivityLog.objects.filter(team_id=self.team.id, scope="Team", item_id=str(self.team.id))
            .order_by("-created_at")
            .first()
        )
        if entry is None or entry.detail is None:
            return []
        return entry.detail["changes"]

    def test_replaces_active_secret_and_logs_the_change(self):
        row = SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_leaked")

        retirement = retire_leaked_signing_secret(self.team.id, "phs_leaked")

        self.assertTrue(retirement.replaced)
        self.assertFalse(retirement.grace_window_ended)
        row.refresh_from_db()
        self.assertNotEqual(row.secret, "phs_leaked")
        self.assertTrue(row.rotated_independently)
        changes = self._changes()
        self.assertEqual([change["field"] for change in changes], ["conversations_signing_secret"])
        # Team members can read this trail, so the new live secret must arrive masked.
        self.assertEqual(changes[0]["after"], mask_key_value(row.secret))

    def test_clears_a_previous_secret_holding_the_token(self):
        from django.utils import timezone

        row = SigningSecret.objects.for_team(self.team.id).create(
            team=self.team,
            secret="phs_rotated_fresh",
            previous_secret="phs_leaked",
            previous_secret_rotated_at=timezone.now(),
            rotated_independently=True,
        )

        retirement = retire_leaked_signing_secret(self.team.id, "phs_leaked")

        # The active secret stays, so nothing was "replaced" for the exposure email, but
        # the grace window ended and the email must say so.
        self.assertFalse(retirement.replaced)
        self.assertTrue(retirement.grace_window_ended)
        row.refresh_from_db()
        self.assertEqual(row.secret, "phs_rotated_fresh")
        self.assertIsNone(row.previous_secret)
        self.assertIsNone(row.previous_secret_rotated_at)
        self.assertIn("conversations_signing_secret_previous", [change["field"] for change in self._changes()])

    def test_leaves_an_unrelated_row_untouched(self):
        row = SigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="phs_unrelated")

        retirement = retire_leaked_signing_secret(self.team.id, "phs_leaked")

        self.assertFalse(retirement.replaced)
        self.assertFalse(retirement.grace_window_ended)
        row.refresh_from_db()
        self.assertEqual(row.secret, "phs_unrelated")
        self.assertFalse(row.rotated_independently)
        self.assertEqual(self._changes(), [])
