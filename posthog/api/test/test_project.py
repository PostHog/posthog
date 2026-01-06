from unittest.mock import MagicMock, patch

from rest_framework import status

from posthog.api.project import ProjectViewSet
from posthog.api.test.test_team import EnvironmentToProjectRewriteClient, team_api_test_factory
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.person import Person
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.project import Project
from posthog.models.utils import generate_random_token_personal


class TestProjectAPI(team_api_test_factory()):  # type: ignore
    """
    We inherit from TestTeamAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient

    def test_projects_outside_personal_api_key_scoped_organizations_not_listed(self):
        other_org, _, team_in_other_org = Organization.objects.bootstrap(self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_organizations=[other_org.id],
        )

        response = self.client.get("/api/projects/", headers={"authorization": f"Bearer {personal_api_key}"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {project["id"] for project in response.json()["results"]},
            {team_in_other_org.project.id},
            "Only the project belonging to the scoped organization should be listed, the other one should be excluded",
        )

    def test_cannot_create_second_demo_project(self):
        # Create first demo project
        Project.objects.create_with_team(
            organization=self.organization, name="First Demo", initiating_user=self.user, team_fields={"is_demo": True}
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Try to create second demo project
        response = self.client.post("/api/projects/", {"name": "Second Demo", "is_demo": True})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You have reached the maximum limit of allowed projects for your current plan. Upgrade your plan to be able to create and manage more projects.",
        )

    def test_project_creation_without_feature(self):
        # Organization without the ORGANIZATIONS_PROJECTS feature (has 1 project already)
        self.organization.available_product_features = []
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "New Project"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You have reached the maximum limit of allowed projects for your current plan. Upgrade your plan to be able to create and manage more projects.",
        )

    def test_project_creation_with_limited_feature(self):
        # Set project limit to 2
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": 2,
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Can create one more project (already have 1)
        response = self.client.post("/api/projects/", {"name": "Second Project"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Cannot create third project
        response = self.client.post("/api/projects/", {"name": "Third Project"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You have reached the maximum limit of allowed projects for your current plan. Upgrade your plan to be able to create and manage more projects.",
        )

    def test_project_creation_with_unlimited_feature(self):
        # Set unlimited projects
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": None,  # unlimited
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Can create multiple projects
        for i in range(5):
            response = self.client.post("/api/projects/", {"name": f"Project {i}"})
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch("posthog.models.organization.Organization.teams")
    def test_hard_limit_projects(self, mock_teams):
        # Set unlimited projects
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": None,  # unlimited
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Mock the teams queryset to return a count of 1500 non-demo projects
        mock_qs = MagicMock()
        mock_qs.exclude.return_value.distinct.return_value.count.return_value = 1500
        mock_teams.return_value = mock_qs
        mock_teams.exclude.return_value.distinct.return_value.count.return_value = 1500

        # Should not be able to create another project
        response = self.client.post("/api/projects/", {"name": "Project 1001"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You have reached the maximum limit of 1500 projects per organization. Contact support if you'd like access to more projects.",
        )

    def test_demo_projects_not_counted_toward_limit(self):
        # Set project limit to 2
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": 2,
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a demo project (doesn't count toward limit)
        Project.objects.create_with_team(
            organization=self.organization,
            name="Demo Project",
            initiating_user=self.user,
            team_fields={"is_demo": True},
        )

        # Can still create 2 regular projects (demo doesn't count)
        response = self.client.post("/api/projects/", {"name": "Regular Project 1"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Can't create third regular project (limit reached)
        response = self.client.post("/api/projects/", {"name": "Regular Project 2"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_project_allowed_regardless_of_limits(self):
        # Set project limit to 1 (already have 1)
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": 1,
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Should be able to update existing project even at limit
        response = self.client.patch(f"/api/projects/{self.project.id}/", {"name": "Updated Name"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Updated Name")

    @patch("posthog.api.project.delete_batch_exports")
    def test_project_deletion_deletes_persons_manually(self, mock_batch_exports):
        """Verify that project deletion deletes Persons via manual delete, not CASCADE."""
        # Create a Person
        person = Person.objects.create(team=self.team)

        # Delete project via API (which calls delete_bulky_postgres_data)
        viewset = ProjectViewSet()
        request = MagicMock()
        request.user = self.user
        viewset.request = request

        viewset.perform_destroy(self.project)

        # Verify Person was deleted (by manual delete, not CASCADE)
        self.assertFalse(Person.objects.filter(id=person.id).exists())

        # Verify project was deleted
        self.assertFalse(Project.objects.filter(id=self.project.id).exists())

    def test_team_deletion_does_not_cascade_to_persons(self):
        """Verify that deleting Team directly doesn't CASCADE delete Persons (on_delete=DO_NOTHING)."""
        # Create a Person
        person = Person.objects.create(team=self.team)
        person_id = person.id

        # Delete the team directly (not via API, bypassing manual delete)
        self.team.delete()

        # Person should still exist (not CASCADE deleted)
        self.assertTrue(Person.objects.filter(id=person_id).exists())

        # Clean up orphaned person using raw delete to bypass signals
        Person.objects.filter(id=person_id)._raw_delete(Person.objects.db)

    def test_complete_product_onboarding_requires_product_type(self):
        response = self.client.patch(
            f"/api/projects/{self.project.id}/complete_product_onboarding/",
            {"intent_context": "onboarding product selected - primary", "metadata": {}},
            headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "product_type is required")

    def test_complete_product_onboarding_rejects_invalid_product_type(self):
        from posthog.schema import ProductKey

        response = self.client.patch(
            f"/api/projects/{self.project.id}/complete_product_onboarding/",
            {
                "product_type": "invalid_product",
                "intent_context": "onboarding product selected - primary",
                "metadata": {},
            },
            headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_message = response.json()["error"]
        self.assertIn("invalid product_type", error_message)
        self.assertIn("expected one of", error_message)

        # Verify it lists valid ProductKey values in the error message
        valid_keys = list(ProductKey)
        self.assertIn(valid_keys[0].value, error_message)  # Check at least one valid key is mentioned

    def test_conversations_settings_merges_with_existing(self):
        self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"conversations_settings": {"widget_greeting_text": "Hello!"}},
        )
        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"conversations_settings": {"widget_color": "#ff0000"}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = response.json()["conversations_settings"]
        self.assertEqual(settings["widget_greeting_text"], "Hello!")
        self.assertEqual(settings["widget_color"], "#ff0000")

    def test_enabling_conversations_auto_generates_token(self):
        self.team.conversations_enabled = False
        self.team.conversations_settings = None
        self.team.save()

        response = self.client.patch(f"/api/projects/{self.project.id}/", {"conversations_enabled": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = response.json()["conversations_settings"]
        self.assertIsNotNone(settings)
        self.assertIsNotNone(settings.get("widget_public_token"))
        self.assertGreater(len(settings["widget_public_token"]), 20)

    def test_generate_conversations_public_token(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(f"/api/projects/{self.project.id}/generate_conversations_public_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        settings = response.json()["conversations_settings"]
        self.assertIsNotNone(settings.get("widget_public_token"))

    def test_generate_conversations_public_token_requires_admin(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(f"/api/projects/{self.project.id}/generate_conversations_public_token/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
