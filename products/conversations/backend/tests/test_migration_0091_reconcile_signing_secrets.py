from typing import Any

from posthog.test.base import TestMigrations

from django.utils import timezone

from posthog.models.team.team import Team
from posthog.models.utils import hash_key_value


class TestReconcileSigningSecrets(TestMigrations):
    """Rollout protection for migration 0091; delete after it has applied everywhere and
    the rollback window has closed (django-migrations: retire dedicated migration tests)."""

    app = "conversations"
    migrate_from = "0090_pylon_issue_uniq"
    migrate_to = "0091_reconcile_signing_secrets"

    def setUp(self) -> None:
        (
            self.drifted_team,
            self.graced_team,
            self.tokenless_team,
            self.independent_team,
            self.revoked_drifted_team,
            self.revoked_synced_team,
        ) = (
            Team.objects.create(organization=self.organization, secret_api_token=token)
            for token in ("phs_current1", "phs_current2", "", "phs_current4", "phs_leaked5", "phs_leaked6")
        )
        super().setUp()

    def setUpBeforeMigration(self, apps: Any) -> None:
        SigningSecret = apps.get_model("conversations", "SigningSecret")
        RevokedTeamSecretToken = apps.get_model("posthog", "RevokedTeamSecretToken")

        def row(team: Team, **kwargs: Any) -> int:
            return SigningSecret.objects.create(team_id=team.id, **kwargs).id

        self.drifted = row(self.drifted_team, secret="phs_retired")
        self.graced = row(
            self.graced_team,
            secret="phs_current2",
            previous_secret="phs_retired_backup",
            previous_secret_rotated_at=timezone.now(),
        )
        self.tokenless = row(self.tokenless_team, secret="phs_orphan")
        self.independent = row(self.independent_team, secret="phs_minted", rotated_independently=True)
        for team, token in ((self.revoked_drifted_team, "phs_leaked5"), (self.revoked_synced_team, "phs_leaked6")):
            RevokedTeamSecretToken.objects.create(team_id=team.id, secure_value=hash_key_value(token))
        self.revoked_drifted = row(self.revoked_drifted_team, secret="phs_retired5")
        self.revoked_synced = row(self.revoked_synced_team, secret="phs_leaked6")

    def test_resyncs_only_rows_still_mirroring_the_token(self) -> None:
        SigningSecret = self.apps.get_model("conversations", "SigningSecret")  # type: ignore[union-attr]
        by_id = {s.pk: s for s in SigningSecret.objects.all()}

        drifted = by_id[self.drifted]
        assert drifted.secret == "phs_current1"
        assert drifted.previous_secret is None
        assert drifted.previous_secret_rotated_at is None

        graced = by_id[self.graced]
        assert graced.secret == "phs_current2"
        assert graced.previous_secret is None
        assert graced.previous_secret_rotated_at is None

        assert by_id[self.tokenless].secret == "phs_orphan"
        assert by_id[self.independent].secret == "phs_minted"

        # A leak-revoked token never becomes the trusted secret, synced or not: the row
        # gets a fresh random value and stops mirroring the column.
        for pk, leaked in ((self.revoked_drifted, "phs_leaked5"), (self.revoked_synced, "phs_leaked6")):
            replaced = by_id[pk]
            assert replaced.secret not in (leaked, "phs_retired5")
            assert replaced.rotated_independently is True
            assert replaced.previous_secret is None
