from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.project import ProjectViewSet
from posthog.api.test.test_team import EnvironmentToProjectRewriteClient, team_api_test_factory
from posthog.constants import AvailableFeature
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.person.util import get_person_by_uuid
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.persons import create_person, delete_person


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
            scopes=["*"],
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

    def _set_unlimited_projects(self, with_member_create_entitlement: bool = True) -> None:
        features: list[dict] = [{"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}]
        if with_member_create_entitlement:
            # members_can_create_projects is gated behind the invite-settings entitlement for now
            features.append({"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS, "name": "Org invite settings"})
        self.organization.available_product_features = features
        self.organization.save()

    def test_member_cannot_create_project_by_default(self):
        self._set_unlimited_projects()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"], "You need to be an organization admin or above to create new projects."
        )

    def test_member_cannot_create_project_without_entitlement_even_when_toggle_on(self):
        # No invite-settings entitlement: the toggle is ignored and the gate behaves as admin-only.
        self._set_unlimited_projects(with_member_create_entitlement=False)
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"], "You need to be an organization admin or above to create new projects."
        )

    def test_member_can_create_project_when_org_allows(self):
        self._set_unlimited_projects()
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with patch("posthog.api.project.create_notification"):
            response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_member_cannot_set_admin_only_fields_when_creating_project(self):
        # A member allowed to create projects must not be able to set admin-only team fields like
        # receive_org_level_activity_logs, which would grant org-wide activity log access.
        self._set_unlimited_projects()
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with patch("posthog.api.project.create_notification"):
            response = self.client.post(
                "/api/projects/", {"name": "Sneaky Project", "receive_org_level_activity_logs": True}
            )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("receive_org_level_activity_logs", response.json()["detail"])
        self.assertFalse(self.organization.teams.filter(receive_org_level_activity_logs=True).exists())

    def test_admin_can_set_admin_only_fields_when_creating_project(self):
        self._set_unlimited_projects()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            "/api/projects/", {"name": "Admin Project", "receive_org_level_activity_logs": True}
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["receive_org_level_activity_logs"])

    @parameterized.expand(
        [
            ("admin", OrganizationMembership.Level.ADMIN),
            ("owner", OrganizationMembership.Level.OWNER),
        ]
    )
    def test_admins_and_owners_can_always_create_project_when_members_blocked(self, _name, level):
        self._set_unlimited_projects()
        self.organization.members_can_create_projects = False
        self.organization.save()
        self.organization_membership.level = level
        self.organization_membership.save()

        with patch("posthog.api.project.create_notification") as mock_create_notification:
            response = self.client.post("/api/projects/", {"name": f"{_name} Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Admins/owners are the recipients, never the trigger — creating their own project must not notify
        mock_create_notification.assert_not_called()

    @patch("posthog.api.project.create_notification")
    def test_member_project_creation_notifies_org_admins(self, mock_create_notification):
        from posthog.models import User

        from products.notifications.backend.facade.api import NotificationType, TargetType

        self._set_unlimited_projects()
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Add an admin so we can confirm admins/owners are targeted individually by user_id
        admin_user = User.objects.create_and_join(
            self.organization, "admin2@posthog.com", None, level=OrganizationMembership.Level.ADMIN
        )
        expected_admin_ids = set(
            self.organization.memberships.filter(level__gte=OrganizationMembership.Level.ADMIN).values_list(
                "user_id", flat=True
            )
        )

        response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # One USER-targeted notification per admin/owner, never the member creator
        self.assertEqual(mock_create_notification.call_count, len(expected_admin_ids))
        targeted_user_ids = set()
        for call in mock_create_notification.call_args_list:
            data = call[0][0]
            self.assertEqual(data.notification_type, NotificationType.PROJECT_CREATED)
            self.assertEqual(data.target_type, TargetType.USER)
            targeted_user_ids.add(int(data.target_id))
        self.assertEqual(targeted_user_ids, expected_admin_ids)
        self.assertIn(admin_user.id, targeted_user_ids)
        self.assertNotIn(self.user.id, targeted_user_ids)

    @patch("posthog.api.project.create_notification")
    def test_admin_project_creation_does_not_notify(self, mock_create_notification):
        self._set_unlimited_projects()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Admin Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_create_notification.assert_not_called()

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

    @patch("posthog.api.project.delete_project_data_and_notify_task")
    def test_project_deletion_queues_async_task(self, mock_delete_task):
        """Verify that project deletion queues async task for full deletion."""
        viewset = ProjectViewSet()
        factory = APIRequestFactory()
        request = factory.delete("/fake")
        request.user = self.user
        viewset.request = request

        project_id = self.project.id
        project_name = self.project.name
        team_id = self.team.id

        viewset.perform_destroy(self.project)

        # Project deletion happens async in Celery task

        mock_delete_task.delay.assert_called_once_with(
            team_ids=[team_id],
            project_id=project_id,
            user_id=self.user.id,
            project_name=project_name,
        )

    @parameterized.expand(
        [
            ("cloud_last_project_active_sub", True, 1, True, True, status.HTTP_400_BAD_REQUEST),
            ("cloud_last_project_no_sub", True, 1, False, True, status.HTTP_204_NO_CONTENT),
            ("cloud_non_last_project_active_sub", True, 2, True, True, status.HTTP_204_NO_CONTENT),
            ("self_hosted", False, 1, True, True, status.HTTP_204_NO_CONTENT),
            ("cloud_no_license", True, 1, True, None, status.HTTP_204_NO_CONTENT),
        ]
    )
    @patch("posthog.api.project.delete_project_data_and_notify_task")
    @patch("ee.billing.billing_manager.BillingManager.get_billing")
    @patch("posthog.api.project.get_cached_instance_license")
    def test_delete_last_project_subscription_guard(
        self,
        _name,
        is_cloud,
        project_count,
        has_active_subscription,
        license_value,
        expected_status,
        mock_get_license,
        mock_get_billing,
        mock_delete_task,
    ):
        mock_get_license.return_value = license_value
        mock_get_billing.return_value = {"has_active_subscription": has_active_subscription}

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        if project_count > 1:
            Project.objects.create_with_team(
                organization=self.organization, name="Second project", initiating_user=self.user
            )

        with self.is_cloud(is_cloud):
            response = self.client.delete(f"/api/projects/{self.project.id}")

        self.assertEqual(response.status_code, expected_status)
        if expected_status == status.HTTP_400_BAD_REQUEST:
            self.assertIn("active subscription", response.json()["detail"])
            self.assertTrue(Project.objects.filter(id=self.project.id).exists())

    @patch("posthog.api.project.delete_project_data_and_notify_task")
    def test_project_deletion_sets_pending_deletion_flag(self, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.delete(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        mock_delete_task.delay.assert_called_once()

    @patch("posthog.api.project.delete_project_data_and_notify_task")
    def test_project_deletion_returns_pending_deletion_in_api(self, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.client.delete(f"/api/projects/{self.project.id}")

        response = self.client.get(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_pending_deletion"])

    @patch("posthog.api.project.delete_project_data_and_notify_task")
    def test_delete_project_already_pending_deletion_returns_400(self, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.project.is_pending_deletion = True
        self.project.save(update_fields=["is_pending_deletion"])

        response = self.client.delete(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already being deleted", response.json()["detail"])
        mock_delete_task.delay.assert_not_called()

    def test_team_deletion_does_not_cascade_to_persons(self):
        """Verify that deleting Team directly doesn't CASCADE delete Persons (on_delete=DO_NOTHING)."""
        # Create a Person
        person = create_person(team=self.team)

        # Delete the team directly (not via API, bypassing manual delete)
        self.team.delete()

        # Person should still exist (not CASCADE deleted). Read by the person's own
        # team_id — self.team.pk is None after delete().
        self.assertIsNotNone(get_person_by_uuid(person.team_id, str(person.uuid)))

        # Clean up orphaned person
        delete_person(person)

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

    def test_project_name_search_filter(self):
        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ORGANIZATIONS_PROJECTS,
                "name": "Projects",
                "limit": None,
            }
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        Project.objects.create_with_team(
            organization=self.organization,
            name="Analytics Dashboard",
            initiating_user=self.user,
        )
        Project.objects.create_with_team(
            organization=self.organization,
            name="Revenue Tracker",
            initiating_user=self.user,
        )
        Project.objects.create_with_team(
            organization=self.organization,
            name="User Analytics",
            initiating_user=self.user,
        )

        response = self.client.get("/api/projects/?search=Analytics")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 2)
        names = {r["name"] for r in results}
        self.assertEqual(names, {"Analytics Dashboard", "User Analytics"})

        response = self.client.get("/api/projects/?search=Revenue")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Revenue Tracker")

        response = self.client.get("/api/projects/?search=nonexistent")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual(len(results), 0)

    def test_read_only_api_key_cannot_update_project_config_fields(self):
        """API keys with only project:read scope should not be able to modify config fields via /api/projects/."""
        api_key = self.create_personal_api_key_with_scopes(["project:read"])

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"timezone": "Europe/Lisbon"},
            headers={"authorization": f"Bearer {api_key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("project:write", response.json().get("detail", ""))

        # Verify no changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "UTC")

    def test_write_api_key_can_update_project_config_fields(self):
        """API keys with project:write scope should be able to modify config fields via /api/projects/."""
        api_key = self.create_personal_api_key_with_scopes(["project:write"])

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
            headers={"authorization": f"Bearer {api_key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "Europe/Lisbon")
        self.assertEqual(self.team.session_recording_opt_in, True)

    def test_read_only_api_key_cannot_update_project_non_config_fields(self):
        """API keys with only project:read scope should not be able to modify non-config fields like name."""
        api_key = self.create_personal_api_key_with_scopes(["project:read"])

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"name": "New Project Name"},
            headers={"authorization": f"Bearer {api_key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify no changes were made
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.name, "New Project Name")

    def test_write_api_key_can_update_project_non_config_fields(self):
        """API keys with project:write scope should be able to modify non-config fields like name."""
        api_key = self.create_personal_api_key_with_scopes(["project:write"])

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"name": "New Project Name"},
            headers={"authorization": f"Bearer {api_key}"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify changes were made
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "New Project Name")

    # --- Parity coverage: fields and actions that previously existed only on /api/environments/ ---

    def test_retrieve_project_includes_environment_parity_fields(self):
        response = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        # Fields that used to be exposed only by /api/environments/ must now appear on /api/projects/ too
        for field in [
            "project_id",
            "user_access_level",
            "managed_viewsets",
            "base_currency",
            "capture_dead_clicks",
            "cookieless_server_hash_mode",
            "default_data_theme",
            "revenue_analytics_config",
            "marketing_analytics_config",
            "customer_analytics_config",
            "web_analytics_pre_aggregated_tables_enabled",
        ]:
            self.assertIn(field, data, f"/api/projects/ response is missing parity field '{field}'")
        # project_id on a Project equals its own id (Project ↔ Team is 1:1)
        self.assertEqual(data["project_id"], self.project.id)

    def test_retrieve_project_does_not_500_when_broker_unavailable(self):
        # Regression: get_product_intents used to call calculate_product_activation.delay()
        # on every retrieve, which 500s the whole endpoint when the broker is down. It now
        # goes through the debounced helper, which fails open on broker errors.
        # Clear the cache so the debounce key is unset and the enqueue path actually runs —
        # otherwise the patched .delay() is never reached and this test passes vacuously.
        cache.clear()
        with patch(
            "posthog.models.product_intent.product_intent.calculate_product_activation.delay",
            side_effect=Exception("broker is unavailable"),
        ) as mock_delay:
            response = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("product_intents", response.json())
        mock_delay.assert_called_once()

    def test_new_passthrough_field_writes_through_to_team(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"base_currency": "EUR", "capture_dead_clicks": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["base_currency"], "EUR")
        self.assertEqual(response.json()["capture_dead_clicks"], True)

        self.team.refresh_from_db()
        self.assertEqual(self.team.base_currency, "EUR")
        self.assertEqual(self.team.capture_dead_clicks, True)

    def test_customer_analytics_config_writes_through_to_team(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"customer_analytics_config": {"activity_event": "$pageview"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["customer_analytics_config"]["activity_event"], "$pageview")

        self.team.refresh_from_db()
        self.assertEqual(self.team.customer_analytics_config.activity_event, "$pageview")

    def test_settings_as_of_action_available_on_projects(self):
        # This action previously existed only on /api/environments/ — it must now work on /api/projects/ too.
        # NOTE: we pass a `scope` filter on purpose. The unscoped snapshot path has a pre-existing bug on the
        # environments endpoint too — TEAM_CONFIG_FIELDS includes the analytics-config *properties* (model
        # instances, not JSON-serializable), so an unscoped call 500s on both surfaces. Faithfully replicated
        # here; fixing it belongs in a separate change since it affects /api/environments/ identically.
        response = self.client.get(
            f"/api/projects/{self.project.id}/settings_as_of/?at=2020-01-01T00:00:00Z&scope=timezone"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("timezone", response.json())

    def test_experiments_config_action_available_on_projects(self):
        response = self.client.get(f"/api/projects/{self.project.id}/experiments_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertIn("default_experiment_stats_method", response.json())
