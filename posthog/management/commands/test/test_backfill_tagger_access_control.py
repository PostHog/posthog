import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

try:
    from ee.models.rbac.access_control import AccessControl
except ImportError:
    pass


@pytest.mark.ee
class TestBackfillTaggerAccessControl(BaseTest):
    def test_creates_tagger_row_for_default_llm_analytics_access_and_is_idempotent(self):
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="viewer")

        # Runs twice on purpose: organization_member/role are nullable, and Postgres treats NULLs as
        # distinct in unique constraints, so a naive create-on-every-run implementation would silently
        # duplicate the default (unscoped) row on a second pass instead of leaving it alone.
        call_command("backfill_tagger_access_control")
        call_command("backfill_tagger_access_control")

        self.assertEqual(AccessControl.objects.filter(resource="tagger").count(), 1)
        tagger_ac = AccessControl.objects.get(team=self.team, resource="tagger", resource_id=None)
        self.assertEqual(tagger_ac.access_level, "viewer")

    def test_copies_member_and_role_scoped_rows(self):
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password123")
        membership = OrganizationMembership.objects.get(user=other_user, organization=self.organization)

        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            organization_member=membership,
            access_level="editor",
        )

        call_command("backfill_tagger_access_control")

        tagger_ac = AccessControl.objects.get(
            team=self.team, resource="tagger", resource_id=None, organization_member=membership
        )
        self.assertEqual(tagger_ac.access_level, "editor")

    def test_does_not_copy_object_level_rows(self):
        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", resource_id="some-dataset-id", access_level="viewer"
        )

        call_command("backfill_tagger_access_control")

        self.assertFalse(AccessControl.objects.filter(resource="tagger").exists())

    def test_updates_existing_tagger_row_when_access_level_diverged(self):
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="editor")
        AccessControl.objects.create(team=self.team, resource="tagger", resource_id=None, access_level="viewer")

        call_command("backfill_tagger_access_control")

        tagger_ac = AccessControl.objects.get(team=self.team, resource="tagger", resource_id=None)
        self.assertEqual(tagger_ac.access_level, "editor")
        self.assertEqual(AccessControl.objects.filter(resource="tagger").count(), 1)

    def test_dry_run_makes_no_changes(self):
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="viewer")

        call_command("backfill_tagger_access_control", "--dry-run")

        self.assertFalse(AccessControl.objects.filter(resource="tagger").exists())

    def test_team_id_filters_to_a_single_team(self):
        other_team = self.organization.teams.create(name="Other team")
        AccessControl.objects.create(team=self.team, resource="llm_analytics", resource_id=None, access_level="viewer")
        AccessControl.objects.create(team=other_team, resource="llm_analytics", resource_id=None, access_level="editor")

        call_command("backfill_tagger_access_control", f"--team-id={self.team.id}")

        self.assertTrue(AccessControl.objects.filter(team=self.team, resource="tagger").exists())
        self.assertFalse(AccessControl.objects.filter(team=other_team, resource="tagger").exists())
