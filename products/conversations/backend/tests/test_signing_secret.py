from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import OperationalError

from parameterized import parameterized

from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team import Team
from posthog.models.team.team_caching import get_team_in_cache
from posthog.test.api_keys import create_project_secret_api_key

from products.conversations.backend.models import SigningSecret


class TestSigningSecret(BaseTest):
    @parameterized.expand(
        [
            ("first_mint", None),
            ("rotation_updates_existing_row", "phs_previous_secret"),
        ]
    )
    def test_token_rotation_dual_writes_signing_secret(self, _name, existing_token):
        # The rotation signal keeps the new store in sync; if it disconnects, the
        # signing secret silently goes stale and post-cutover verification breaks.
        self.team.secret_api_token = existing_token
        self.team.save()
        if existing_token:
            SigningSecret.objects.for_team(self.team.id).update_or_create(
                team=self.team, defaults={"secret": existing_token}
            )

        self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)

        row = SigningSecret.objects.for_team(self.team.id).get()
        self.assertEqual(row.secret, self.team.secret_api_token)
        self.assertEqual(SigningSecret.objects.for_team(self.team.id).count(), 1)

    def test_failed_signing_secret_write_rolls_the_rotation_back(self):
        # The two stores must never diverge: if the signing-secret copy fails, the
        # legacy column must keep its old value instead of rotating alone.
        self.team.secret_api_token = "phs_previous_secret"
        self.team.secret_api_token_backup = "phs_expired_backup"
        self.team.save()
        SigningSecret.objects.for_team(self.team.id).update_or_create(
            team=self.team, defaults={"secret": "phs_previous_secret"}
        )
        # A migrated PSAK row (#63111) for the backup the rotation was about to retire
        # must survive the rollback along with the backup token itself.
        backup_row, _ = create_project_secret_api_key(
            self.team, label="Migrated legacy key (backup)", value="phs_expired_backup"
        )

        with patch.object(SigningSecret.objects, "for_team", side_effect=OperationalError("connection lost")):
            with self.assertRaises(OperationalError):
                self.team.rotate_secret_token_and_save(user=self.user, is_impersonated_session=False)

        self.team.refresh_from_db()
        self.assertEqual(self.team.secret_api_token, "phs_previous_secret")
        self.assertEqual(self.team.secret_api_token_backup, "phs_expired_backup")
        self.assertEqual(SigningSecret.objects.for_team(self.team.id).get().secret, "phs_previous_secret")
        # The post_save hook cached the team mid-transaction; the failure path must
        # rewrite that entry so the cache never holds the rolled-back tokens.
        cached = get_team_in_cache(self.team.api_token)
        assert cached is not None
        self.assertEqual(cached.secret_api_token, "phs_previous_secret")
        self.assertEqual(cached.secret_api_token_backup, "phs_expired_backup")
        self.assertTrue(ProjectSecretAPIKey.objects.filter(pk=backup_row.pk).exists())

    def test_failed_backup_cleanup_rolls_the_deletion_back(self):
        self.team.secret_api_token = "phs_current_primary_value"
        self.team.secret_api_token_backup = "phs_backup_pending_deletion"
        self.team.save()
        backup_row, _ = create_project_secret_api_key(
            self.team, label="Migrated legacy key (backup)", value="phs_backup_pending_deletion"
        )

        with patch(
            "posthog.models.team.team.delete_project_secret_api_keys_for_token",
            side_effect=OperationalError("connection lost"),
        ):
            with self.assertRaises(OperationalError):
                self.team.delete_secret_token_backup_and_save(user=self.user, is_impersonated_session=False)

        # The rollback must restore the instance and the cache, so a retry actually retries.
        self.assertEqual(self.team.secret_api_token_backup, "phs_backup_pending_deletion")
        cached = get_team_in_cache(self.team.api_token)
        assert cached is not None
        self.assertEqual(cached.secret_api_token_backup, "phs_backup_pending_deletion")
        self.assertTrue(ProjectSecretAPIKey.objects.filter(pk=backup_row.pk).exists())

    def test_child_environment_keeps_its_own_team_on_save(self):
        # Environment-scoped by design: a canonicalizing save() (RootTeamMixin) would rewrite
        # the child's row to the parent team, sharing one secret across sibling environments
        # and making per-environment copy rows collide on the OneToOne constraint.
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )

        parent_secret = SigningSecret(team=self.team, secret="phs_parent_secret")
        parent_secret.save()
        child_secret = SigningSecret(team=child_team, secret="phs_child_secret")
        child_secret.save()

        child_secret.refresh_from_db()
        self.assertEqual(child_secret.team_id, child_team.id)
        self.assertEqual(SigningSecret.objects.unscoped().filter(team_id__in=[self.team.id, child_team.id]).count(), 2)
        self.assertEqual(SigningSecret.objects.for_team(child_team.id).get().secret, "phs_child_secret")
