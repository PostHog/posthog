from typing import Any

import pytest
from posthog.test.base import NonAtomicTestMigrations

pytestmark = pytest.mark.skip("old migrations slow overall test run down")


class GuestModeDataModelMigrationTest(NonAtomicTestMigrations):
    migrate_from = "1100_add_subscription_summary_fields"
    migrate_to = "1101_guest_mode_data_model"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        OrganizationInvite = apps.get_model("posthog", "OrganizationInvite")
        OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
        User = apps.get_model("posthog", "User")

        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(organization=self.organization, name="Test Project", id=1000001)
        self.team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            name="Test Team",
        )
        self.user = User.objects.create(email="seed@example.com")
        self.membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            level=1,
        )
        self.invite = OrganizationInvite.objects.create(
            organization=self.organization,
            target_email="invitee@example.com",
        )

    def test_new_fields_exist_with_defaults_and_grant_insertable(self) -> None:
        # Post-migration models are retrieved through self.apps (set by the BaseTestMigrations setUp).
        assert self.apps is not None
        PostMigrationMembership = self.apps.get_model("posthog", "OrganizationMembership")
        PostMigrationInvite = self.apps.get_model("posthog", "OrganizationInvite")
        PostMigrationTeam = self.apps.get_model("posthog", "Team")
        GuestResourceGrant = self.apps.get_model("posthog", "GuestResourceGrant")

        membership = PostMigrationMembership.objects.get(id=self.membership.id)
        self.assertFalse(membership.is_guest)

        invite = PostMigrationInvite.objects.get(id=self.invite.id)
        self.assertEqual(invite.guest_resources, [])
        self.assertFalse(invite.bypass_sso)

        team = PostMigrationTeam.objects.get(id=self.team.id)
        grant = GuestResourceGrant.objects.create(
            organization_membership=membership,
            team=team,
            resource="dashboard",
            resource_id="1",
            is_pending=False,
        )
        self.assertEqual(grant.resource, "dashboard")
        self.assertEqual(grant.resource_id, "1")
