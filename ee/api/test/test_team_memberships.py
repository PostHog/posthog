from rest_framework import status

from ee.api.test.base import APILicensedTest
from ee.models.explicit_team_membership import ExplicitTeamMembership
from posthog.models import OrganizationMembership, Team, User


class TestTeamMembershipsAPI(APILicensedTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.team.access_control = True
        self.team.save()

    def test_add_member_as_org_owner_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.MEMBER, "level": ExplicitTeamMembership.Level.MEMBER,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

    def test_add_member_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.MEMBER, "level": ExplicitTeamMembership.Level.MEMBER,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

    def test_add_member_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

    def test_add_yourself_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.assertEqual(self.team.explicit_memberships.count(), 0)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": self.user.uuid})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

    def test_add_yourself_as_org_admin_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.assertEqual(self.team.explicit_memberships.count(), 0)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": self.user.uuid})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You can't explicitly add yourself to projects."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self.team.explicit_memberships.count(), 0)

    def test_add_member_as_org_member_and_project_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

    def test_add_member_as_org_member_but_project_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        self.assertEqual(self.team.explicit_memberships.count(), 1)

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.MEMBER, "level": ExplicitTeamMembership.Level.MEMBER,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(self.team.explicit_memberships.count(), 2)

    def test_add_member_as_org_admin_and_project_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.MEMBER, "level": ExplicitTeamMembership.Level.MEMBER,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_add_admin_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post(
            "/api/projects/@current/explicit_members/",
            {"user_uuid": new_user.uuid, "level": ExplicitTeamMembership.Level.ADMIN},
        )
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.ADMIN, "level": ExplicitTeamMembership.Level.ADMIN,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_add_admin_as_project_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post(
            "/api/projects/@current/explicit_members/",
            {"user_uuid": new_user.uuid, "level": ExplicitTeamMembership.Level.ADMIN},
        )
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_admin_as_project_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post(
            "/api/projects/@current/explicit_members/",
            {"user_uuid": new_user.uuid, "level": ExplicitTeamMembership.Level.ADMIN},
        )
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.ADMIN, "level": ExplicitTeamMembership.Level.ADMIN,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_add_member_to_non_current_project_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        another_team = Team.objects.create(organization=self.organization, access_control=True)

        new_user: User = User.objects.create_and_join(
            self.organization, "rookie@posthog.com", None,
        )

        response = self.client.post(f"/api/projects/{another_team.id}/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.MEMBER, "level": ExplicitTeamMembership.Level.MEMBER,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_add_member_to_project_in_outside_organization_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        _, new_team, new_user = User.objects.bootstrap(
            "Acme", "mallory@acme.com", None, team_fields={"access_control": True}
        )

        response = self.client.post(f"/api/projects/{new_team.id}/explicit_members/", {"user_uuid": new_user.uuid,})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_member_to_project_that_is_not_organization_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        _, new_team, new_user = User.objects.bootstrap("Acme", "mallory@acme.com", None)

        response = self.client.post(f"/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid,})
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You both need to belong to the same organization."), response_data
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_add_member_to_nonexistent_project_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post(f"/api/projects/2137/explicit_members/", {"user_uuid": new_user.uuid,})
        response_data = response.json()

        self.assertDictEqual(self.not_found_response("Project not found."), response_data)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_level_of_member_to_admin_as_org_owner_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.patch(
            f"/api/projects/@current/explicit_members/{new_user.uuid}", {"level": ExplicitTeamMembership.Level.ADMIN}
        )
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.ADMIN, "level": ExplicitTeamMembership.Level.ADMIN,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_set_level_of_member_to_admin_as_org_member_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.patch(
            f"/api/projects/@current/explicit_members/{new_user.uuid}", {"level": ExplicitTeamMembership.Level.ADMIN}
        )
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You don't have sufficient permissions in the project."), response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_demote_yourself_as_org_member_and_project_admin_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        response = self.client.patch(
            f"/api/projects/@current/explicit_members/{self.user.uuid}", {"level": ExplicitTeamMembership.Level.MEMBER}
        )
        response_data = response.json()

        self.assertDictEqual(
            self.permission_denied_response("You can't set your own access level."), response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_set_level_of_member_to_admin_as_org_member_but_project_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.patch(
            f"/api/projects/@current/explicit_members/{new_user.uuid}", {"level": ExplicitTeamMembership.Level.ADMIN}
        )
        response_data = response.json()

        self.assertDictContainsSubset(
            {"effective_level": ExplicitTeamMembership.Level.ADMIN, "level": ExplicitTeamMembership.Level.ADMIN,},
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_remove_member_as_org_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.delete(f"/api/projects/@current/explicit_members/{new_user.uuid}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_remove_member_as_org_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.delete(f"/api/projects/@current/explicit_members/{new_user.uuid}")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_remove_member_as_org_member_but_project_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)
        new_org_membership: OrganizationMembership = OrganizationMembership.objects.get(
            user=new_user, organization=self.organization
        )
        new_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=new_org_membership
        )

        response = self.client.delete(f"/api/projects/@current/explicit_members/{new_user.uuid}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_add_member_to_non_private_project_forbidden(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        self.team.access_control = False
        self.team.save()

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        response = self.client.post("/api/projects/@current/explicit_members/", {"user_uuid": new_user.uuid})
        response_data = response.json()

        self.assertDictEqual(
            self.validation_error_response(
                "Explicit members can only be accessed for projects with project-based permissioning enabled.",
            ),
            response_data,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_leave_project_as_admin_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        explicit_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )

        response = self.client.delete(f"/api/projects/@current/explicit_members/{self.user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_leave_project_as_admin_member(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        explicit_team_membership = ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.MEMBER
        )

        response = self.client.delete(f"/api/projects/@current/explicit_members/{self.user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_leave_project_as_project_outsider(self):
        response = self.client.delete(f"/api/projects/@current/explicit_members/{self.user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_leave_project_as_organization_outsider(self):
        self.organization_membership.delete()

        response = self.client.delete(f"/api/projects/@current/explicit_members/{self.user.uuid}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_current_project_no_access(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        ExplicitTeamMembership.objects.create(
            team=self.team, parent_membership=self.organization_membership, level=ExplicitTeamMembership.Level.ADMIN
        )
        team2 = Team.objects.create(organization=self.organization)

        new_user: User = User.objects.create_and_join(self.organization, "rookie@posthog.com", None)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

        self.client.force_login(new_user)
        response = self.client.patch("/api/users/@me/", {"set_current_team": self.team.pk})
        self.maxDiff = None
        response_data = response.json()

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.content)
        self.assertEqual("does_not_exist", response_data["code"], response_data)

        self.assertEqual(self.team.explicit_memberships.count(), 1)

        # If user is admin, allow change
        OrganizationMembership.objects.filter(user=new_user).update(level=OrganizationMembership.Level.ADMIN)
        response = self.client.patch("/api/users/@me/", {"set_current_team": self.team.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
