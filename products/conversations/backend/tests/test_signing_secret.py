from posthog.test.base import BaseTest

from posthog.models.team import Team

from products.conversations.backend.models import SigningSecret


class TestSigningSecret(BaseTest):
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
        self.assertEqual(SigningSecret.objects.unscoped().count(), 2)
        self.assertEqual(SigningSecret.objects.for_team(child_team.id).get().secret, "phs_child_secret")
