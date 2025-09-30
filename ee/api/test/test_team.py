import uuid
from typing import Optional

from freezegun import freeze_time
from posthog.test.base import FuzzyInt
from unittest.mock import patch

from rest_framework.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from posthog.api.test.test_team import EnvironmentToProjectRewriteClient
from posthog.models.dashboard import Dashboard
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.team.team_caching import get_team_in_cache
from posthog.models.user import User

from ee.api.test.base import APILicensedTest
from ee.models.rbac.access_control import AccessControl


def team_enterprise_api_test_factory():
    class TestTeamEnterpriseAPI(APILicensedTest):
        CLASS_DATA_LEVEL_SETUP = False

        def _assert_activity_log(self, expected: list[dict], team_id: Optional[int] = None) -> None:
            if not team_id:
                team_id = self.team.pk

            starting_log_response = self.client.get(f"/api/environments/{team_id}/activity")
            assert starting_log_response.status_code == 200, starting_log_response.json()
            assert starting_log_response.json()["results"] == expected

        # Creating projects

        def test_non_admin_cannot_create_team(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            count = Team.objects.count()
            response = self.client.post("/api/projects/@current/environments/", {"name": "Test"})
            self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
            self.assertEqual(Team.objects.count(), count)
            self.assertEqual(
                response.json(),
                self.permission_denied_response("Your organization access level is insufficient."),
            )

        def test_cannot_create_team_with_primary_dashboard_id(self):
            dashboard_x = Dashboard.objects.create(team=self.team, name="Test")
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            response = self.client.post(
                "/api/projects/@current/environments/", {"name": "Test", "primary_dashboard": dashboard_x.id}
            )
            self.assertEqual(response.status_code, HTTP_400_BAD_REQUEST, response.json())
            self.assertEqual(
                response.json(),
                self.validation_error_response(
                    "Primary dashboard cannot be set on project creation.", attr="primary_dashboard"
                ),
            )

        @patch("posthog.demo.matrix.manager.MatrixManager.run_on_team")  # We don't actually need demo data, it's slow
        def test_create_demo_team(self, *args):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            self.assertEqual(Team.objects.count(), 1)
            response = self.client.post("/api/projects/@current/environments/", {"name": "Hedgebox", "is_demo": True})
            self.assertEqual(response.status_code, 201, response.json())
            self.assertEqual(Team.objects.count(), 2)
            response_data = response.json()
            self.assertDictContainsSubset(
                {
                    "name": "Hedgebox",
                    "access_control": False,
                    "effective_membership_level": OrganizationMembership.Level.ADMIN,
                },
                response_data,
            )
            self.assertEqual(self.organization.teams.count(), 2)

        @patch("posthog.demo.matrix.manager.MatrixManager.run_on_team")  # We don't actually need demo data, it's slow
        def test_create_two_demo_teams(self, *args):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            self.assertEqual(Team.objects.count(), 1)
            response = self.client.post("/api/projects/@current/environments/", {"name": "Hedgebox", "is_demo": True})
            self.assertEqual(response.status_code, 201, response.json())
            self.assertEqual(Team.objects.count(), 2)

            response_data = response.json()
            self.assertDictContainsSubset(
                {
                    "name": "Hedgebox",
                    "access_control": False,
                    "effective_membership_level": OrganizationMembership.Level.ADMIN,
                },
                response_data,
            )
            response_2 = self.client.post("/api/projects/@current/environments/", {"name": "Hedgebox", "is_demo": True})
            self.assertEqual(Team.objects.count(), 2, response_2.json())
            response_2_data = response_2.json()
            self.assertEqual(
                response_2_data.get("detail"),
                "You have reached the maximum limit of allowed environments for your current plan. Upgrade your plan to be able to create and manage more environments."
                if self.client_class is not EnvironmentToProjectRewriteClient
                else "You have reached the maximum limit of allowed projects for your current plan. Upgrade your plan to be able to create and manage more projects.",
            )
            self.assertEqual(response_2_data.get("type"), "authentication_error")
            self.assertEqual(response_2_data.get("code"), "permission_denied")
            self.assertEqual(self.organization.teams.count(), 2)

        # Deleting projects

        def test_delete_team_as_org_admin_allowed(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            response = self.client.delete(f"/api/environments/{self.team.id}")
            self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)
            self.assertEqual(Team.objects.filter(organization=self.organization).count(), 0)

        def test_delete_team_as_org_member_forbidden(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            response = self.client.delete(f"/api/environments/{self.team.id}")
            self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
            self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

        def test_delete_second_team_as_org_admin_allowed(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            team = Team.objects.create(organization=self.organization)
            response = self.client.delete(f"/api/environments/{team.id}")
            self.assertEqual(response.status_code, HTTP_204_NO_CONTENT)
            self.assertEqual(Team.objects.filter(organization=self.organization).count(), 1)

        def test_no_delete_team_not_administrating_organization(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            team = Team.objects.create(organization=self.organization)
            response = self.client.delete(f"/api/environments/{team.id}")
            self.assertEqual(response.status_code, HTTP_403_FORBIDDEN)
            self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

        def test_no_delete_team_not_belonging_to_organization(self):
            team_1 = Organization.objects.bootstrap(None)[2]
            response = self.client.delete(f"/api/environments/{team_1.id}")
            self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
            self.assertTrue(Team.objects.filter(id=team_1.id).exists())
            organization, _, _ = User.objects.bootstrap("X", "someone@x.com", "qwerty", "Someone")
            team_2 = Team.objects.create(organization=organization)
            response = self.client.delete(f"/api/environments/{team_2.id}")
            self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
            self.assertEqual(Team.objects.filter(organization=organization).count(), 2)

        # Updating projects

        def test_can_update_and_retrieve_person_property_names_excluded_from_correlation(self):
            response = self.client.patch(
                f"/api/environments/@current/",
                {"correlation_config": {"excluded_person_property_names": ["$os"]}},
            )
            self.assertEqual(response.status_code, HTTP_200_OK)

            response = self.client.get(f"/api/environments/@current/")
            self.assertEqual(response.status_code, HTTP_200_OK)

            response_data = response.json()

            self.assertDictContainsSubset(
                {"correlation_config": {"excluded_person_property_names": ["$os"]}},
                response_data,
            )

        # Fetching projects

        def test_fetch_team_as_org_admin_works(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.get(f"/api/environments/@current/")
            response_data = response.json()

            self.assertEqual(response.status_code, HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "name": "Default project",
                    "access_control": False,
                    "effective_membership_level": OrganizationMembership.Level.ADMIN,
                },
                response_data,
            )

        def test_fetch_team_as_org_member_works(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()

            response = self.client.get(f"/api/environments/@current/")
            response_data = response.json()

            self.assertEqual(response.status_code, HTTP_200_OK)
            self.assertDictContainsSubset(
                {
                    "name": "Default project",
                    "access_control": False,
                    "effective_membership_level": OrganizationMembership.Level.MEMBER,
                },
                response_data,
            )

        def test_fetch_team_as_org_outsider(self):
            self.organization_membership.delete()
            response = self.client.get(f"/api/environments/@current/")
            response_data = response.json()

            self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
            self.assertEqual(self.not_found_response(), response_data)

        def test_fetch_nonexistent_team(self):
            response = self.client.get(f"/api/environments/234444/")
            response_data = response.json()

            self.assertEqual(response.status_code, HTTP_404_NOT_FOUND)
            self.assertEqual(self.not_found_response(), response_data)

        @freeze_time("2022-02-08")
        def test_team_creation_is_in_activity_log(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            team_name = str(uuid.uuid4())
            response = self.client.post("/api/projects/@current/environments/", {"name": team_name, "is_demo": False})
            self.assertEqual(response.status_code, 201, response.json())

            team_id = response.json()["id"]
            self._assert_activity_log(
                [
                    {
                        "activity": "created",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": None,
                            "name": team_name,
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(team_id),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ],
                team_id=team_id,
            )

        def test_team_is_cached_on_create_and_update(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.post("/api/projects/@current/environments/", {"name": "Test", "is_demo": False})
            self.assertEqual(response.status_code, 201, response.json())
            self.assertEqual(response.json()["name"], "Test")

            token = response.json()["api_token"]
            team_id = response.json()["id"]

            cached_team = get_team_in_cache(token)

            assert cached_team is not None
            self.assertEqual(cached_team.name, "Test")
            self.assertEqual(cached_team.uuid, response.json()["uuid"])
            self.assertEqual(cached_team.id, response.json()["id"])

            response = self.client.patch(
                f"/api/environments/{team_id}/",
                {"timezone": "Europe/Istanbul", "session_recording_opt_in": True},
            )
            self.assertEqual(response.status_code, 200)

            cached_team = get_team_in_cache(token)
            assert cached_team is not None

            self.assertEqual(cached_team.name, "Test")
            self.assertEqual(cached_team.uuid, response.json()["uuid"])
            self.assertEqual(cached_team.session_recording_opt_in, True)

            # only things in CachedTeamSerializer are cached!
            self.assertEqual(cached_team.timezone, "UTC")

            # reset token should update cache as well
            response = self.client.patch(f"/api/environments/{team_id}/reset_token/")
            response_data = response.json()

            cached_team = get_team_in_cache(token)
            assert cached_team is None

            cached_team = get_team_in_cache(response_data["api_token"])
            assert cached_team is not None
            self.assertEqual(cached_team.name, "Test")
            self.assertEqual(cached_team.uuid, response.json()["uuid"])
            self.assertEqual(cached_team.session_recording_opt_in, True)

    return TestTeamEnterpriseAPI


class TestTeamEnterpriseAPI(team_enterprise_api_test_factory()):
    def test_create_team(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        response = self.client.post("/api/projects/@current/environments/", {"name": "Test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Team.objects.count(), 2)
        self.assertEqual(Project.objects.count(), 1)  # Created under the same project, not a new one!
        response_data = response.json()
        self.assertDictContainsSubset(
            {
                "name": "Test",
                "access_control": False,
                "effective_membership_level": OrganizationMembership.Level.ADMIN,
            },
            response_data,
        )
        self.assertEqual(self.organization.teams.count(), 2)

    def test_cannot_create_team_not_under_project(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        response = self.client.post("/api/environments/", {"name": "Test"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Team.objects.count(), 1)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(
            response.json(),
            self.validation_error_response(
                "Environments must be created under a specific project. Send the POST request to /api/projects/<project_id>/environments/ instead."
            ),
        )

    def test_cannot_create_team_in_nonexistent_project(self):
        _, _, team = Organization.objects.bootstrap(self.user, name="other_org")
        self.organization_membership.delete()

        response = self.client.post("/api/projects/4444444/environments/", {"name": "Test"})

        self.assertEqual(response.status_code, 404, response.json())
        self.assertEqual(response.json(), self.not_found_response("Project not found."))

    def test_cannot_create_team_in_project_without_org_access(self):
        self.organization_membership.delete()

        response = self.client.post(f"/api/projects/{self.project.id}/environments/", {"name": "Test"})

        self.assertEqual(response.status_code, 404, response.json())
        self.assertEqual(
            response.json(),
            self.not_found_response("Organization not found."),
        )

    def test_rename_team_as_org_member_allowed(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(f"/api/environments/@current/", {"name": "Erinaceus europaeus"})
        self.team.refresh_from_db()

        self.assertEqual(response.status_code, HTTP_200_OK)
        self.assertEqual(self.team.name, "Erinaceus europaeus")

    def test_list_teams_restricted_ones_hidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        other_team = Team.objects.create(
            organization=self.organization,
            name="Other",
        )

        # Set up new access control system - restrict project to no default access
        AccessControl.objects.create(
            team=other_team,
            access_level="none",
            resource="project",
            resource_id=str(other_team.id),
        )

        # The other team should not be returned as it's restricted for the logged-in user
        projects_response = self.client.get(f"/api/environments/")

        # 9 (above):
        with self.assertNumQueries(FuzzyInt(16, 18)):
            current_org_response = self.client.get(f"/api/organizations/{self.organization.id}/")

        self.assertEqual(projects_response.status_code, HTTP_200_OK)
        self.assertEqual(
            projects_response.json().get("results"),
            [
                {
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "organization": str(self.organization.id),
                    "project_id": self.team.project.id,
                    "api_token": self.team.api_token,
                    "name": self.team.name,
                    "completed_snippet_onboarding": False,
                    "has_completed_onboarding_for": {"product_analytics": True},
                    "ingested_event": False,
                    "is_demo": False,
                    "timezone": "UTC",
                    "access_control": False,
                }
            ],
        )
        self.assertEqual(current_org_response.status_code, HTTP_200_OK)
        self.assertEqual(
            current_org_response.json().get("teams"),
            [
                {
                    "id": self.team.id,
                    "uuid": str(self.team.uuid),
                    "organization": str(self.organization.id),
                    "project_id": self.team.project.id,
                    "api_token": self.team.api_token,
                    "name": self.team.name,
                    "completed_snippet_onboarding": False,
                    "has_completed_onboarding_for": {"product_analytics": True},
                    "ingested_event": False,
                    "is_demo": False,
                    "timezone": "UTC",
                    "access_control": False,
                }
            ],
        )
