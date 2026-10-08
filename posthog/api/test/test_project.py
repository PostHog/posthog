from datetime import timedelta
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import DatabaseError
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIRequestFactory

from posthog.api.project import ProjectBackwardCompatSerializer, ProjectCreateRequestSerializer, ProjectViewSet
from posthog.api.project_tags import MAX_TAGS_PER_FILTER
from posthog.api.team import TeamCustomerAnalyticsConfigSerializer, TeamSerializer
from posthog.api.test.test_team import EnvironmentToProjectRewriteClient, team_api_test_factory
from posthog.constants import AvailableFeature
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.person.util import get_person_by_uuid
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.project import Project
from posthog.models.tag import Tag
from posthog.models.team.extensions import get_or_create_team_extension
from posthog.models.team.team import Team
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.db_context_capturing import capture_db_queries
from posthog.test.persons import create_person, delete_person

from products.customer_analytics.backend.facade.team_extension import TeamCustomerAnalyticsConfig
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig


class TestProjectAPI(team_api_test_factory()):  # type: ignore
    """
    We inherit from TestTeamAPI, as previously /api/projects/ referred to the Team model, which used to mean "project".
    Now as Team means "environment" and Project is separate, we must ensure backward compatibility of /api/projects/.
    At the same time, this class is where we can continue adding `Project`-specific API tests.
    """

    client_class = EnvironmentToProjectRewriteClient

    def test_project_create_request_excludes_response_only_fields(self) -> None:
        serializer = ProjectCreateRequestSerializer()
        self.assertIn("name", serializer.fields)
        self.assertFalse(any(field.required for field in serializer.fields.values()))
        for field_name in ("id", "organization", "created_at", "api_token", "home_tab_dashboard"):
            self.assertNotIn(field_name, serializer.fields)
        self.assertFalse(any(field.read_only for field in serializer.fields.values()))

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

    @parameterized.expand(
        [
            ("exact_match", "Hedgebox"),
            ("different_case", "HEDGEBOX"),
            ("surrounding_whitespace", "  Hedgebox  "),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_cannot_create_project_with_duplicate_name_in_same_organization(self, _name, duplicate_name):
        self._set_unlimited_projects()
        Project.objects.create_with_team(organization=self.organization, name="Hedgebox", initiating_user=self.user)

        response = self.client.post("/api/projects/", {"name": duplicate_name})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already a project called", response.json()["detail"])
        self.assertEqual(Project.objects.filter(organization=self.organization, name__iexact="hedgebox").count(), 1)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_cannot_create_project_duplicating_a_stored_name_with_whitespace(self):
        # The stored side is trimmed too: a legacy name saved with surrounding whitespace
        # still blocks its clean form (and vice versa is covered by the parameterized test)
        self._set_unlimited_projects()
        Project.objects.create_with_team(organization=self.organization, name="  Hedgebox  ", initiating_user=self.user)

        response = self.client.post("/api/projects/", {"name": "Hedgebox"})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already a project called", response.json()["detail"])

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_can_create_project_with_same_name_as_project_in_another_organization(self):
        self._set_unlimited_projects()
        other_organization = Organization.objects.create(name="Other org")
        Project.objects.create_with_team(organization=other_organization, name="Hedgebox", initiating_user=None)

        response = self.client.post("/api/projects/", {"name": "Hedgebox"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "Hedgebox")

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_cannot_create_project_with_pending_duplicate_name(self):
        self._set_unlimited_projects()
        self.project.is_pending_deletion = True
        self.project.save(update_fields=["is_pending_deletion"])

        response = self.client.post("/api/projects/", {"name": self.project.name})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already a project called", response.json()["detail"])

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_creating_projects_without_name_generates_unique_default_names(self):
        self._set_unlimited_projects()
        # The fixture project already holds the plain default name
        self.assertEqual(self.project.name, "Default project")

        first_response = self.client.post("/api/projects/", {})
        second_response = self.client.post("/api/projects/", {})

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first_response.json()["name"], "Default project 2")
        self.assertEqual(second_response.json()["name"], "Default project 3")

    def test_cannot_rename_project_to_duplicate_name(self):
        Project.objects.create_with_team(organization=self.organization, name="Hedgebox", initiating_user=self.user)

        response = self.client.patch(f"/api/projects/{self.project.id}/", {"name": "hedgebox"})

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("already a project called", response.json()["detail"])
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Default project")

    def test_preexisting_projects_with_duplicate_names_can_still_be_updated(self):
        # Duplicates created before the uniqueness rule must keep working, including saves that
        # resubmit the unchanged name alongside other fields
        duplicate_project, _ = Project.objects.create_with_team(
            organization=self.organization, name=self.project.name, initiating_user=self.user
        )

        response = self.client.patch(
            f"/api/projects/{duplicate_project.id}/",
            {"name": duplicate_project.name, "product_description": "still saveable"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        duplicate_project.refresh_from_db()
        self.assertEqual(duplicate_project.product_description, "still saveable")

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

    @override_settings(CLOUD_DEPLOYMENT="US")
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

    @override_settings(CLOUD_DEPLOYMENT="US")
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

    @parameterized.expand([("limited", 2), ("unlimited", None)])
    @override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
    def test_hobby_project_limit_ignores_legacy_entitlement(self, _name, limit):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": limit}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Second Project"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
    def test_hobby_can_create_first_non_demo_project(self):
        self.team.is_demo = True
        self.team.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "First Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
    def test_hobby_can_update_existing_project_with_legacy_entitlement(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 2}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.patch(f"/api/projects/{self.project.id}/", {"name": "Renamed project"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    @override_settings(CLOUD_DEPLOYMENT=None, DEBUG=False)
    def test_hobby_legacy_entitlement_allows_one_demo_but_not_a_second_project(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 2}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        demo_response = self.client.post("/api/projects/", {"name": "Demo", "is_demo": True}, format="json")
        duplicate_demo_response = self.client.post(
            "/api/projects/", {"name": "Another demo", "is_demo": True}, format="json"
        )
        second_project_response = self.client.post(
            "/api/projects/", {"name": "Second project", "is_demo": "false"}, format="json"
        )

        self.assertEqual(demo_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate_demo_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(second_project_response.status_code, status.HTTP_403_FORBIDDEN)

    def _set_unlimited_projects(self, with_member_create_entitlement: bool = True) -> None:
        features: list[dict] = [{"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}]
        if with_member_create_entitlement:
            # members_can_create_projects is gated behind the invite-settings entitlement for now
            features.append({"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS, "name": "Org invite settings"})
        self.organization.available_product_features = features
        self.organization.save()

    def _set_unlimited_projects_with_logs_retention(self, *features: AvailableFeature) -> None:
        self._set_unlimited_projects()
        self.organization.available_product_features = [
            *(self.organization.available_product_features or []),
            *[{"key": feature.value, "name": feature.value.replace("_", " ")} for feature in features],
        ]
        self.organization.save()

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_creation_drops_ai_context_account_property_ids(self):
        self._set_unlimited_projects()
        from products.customer_analytics.backend.facade.testing import create_custom_property_definition

        definition = create_custom_property_definition(team_id=self.team.id, name="Plan", target_type="account")

        created = self.client.post(
            "/api/projects/",
            {
                "name": "Fresh",
                "conversations_settings": {"ai_context_account_property_ids": [str(definition.id)]},
            },
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        # The new project's team owns no property definition, so an id borrowed from another
        # team must not survive creation.
        assert created.json()["conversations_settings"]["ai_context_account_property_ids"] == []

        malformed = self.client.post(
            "/api/projects/",
            {"name": "Malformed", "conversations_settings": {"ai_context_account_property_ids": ["not-a-uuid"]}},
            format="json",
        )
        assert malformed.status_code == status.HTTP_400_BAD_REQUEST

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_creation_rejects_paid_logs_retention_without_feature(self):
        self._set_unlimited_projects()

        response = self.client.post(
            "/api/projects/",
            {"name": "Logs Project", "logs_settings": {"retention_days": 30}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("30 days", response.json()["detail"])

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_creation_allows_base_logs_retention_without_feature(self):
        self._set_unlimited_projects()

        response = self.client.post(
            "/api/projects/",
            {"name": "Logs Project", "logs_settings": {"retention_days": 14}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["logs_settings"]["retention_days"], 14)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_creation_allows_paid_logs_retention_with_matching_feature(self):
        self._set_unlimited_projects_with_logs_retention(AvailableFeature.LOGS_RETENTION_30D)

        response = self.client.post(
            "/api/projects/",
            {"name": "Logs Project", "logs_settings": {"retention_days": 30}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["logs_settings"]["retention_days"], 30)

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_creation_rejects_invalid_logs_retention(self):
        self._set_unlimited_projects()

        response = self.client.post(
            "/api/projects/",
            {"name": "Logs Project", "logs_settings": {"retention_days": 45}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("retention_days must be one of", response.json()["detail"])

    def test_member_cannot_create_project_by_default(self):
        self._set_unlimited_projects()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"], "You need to be an organization admin or above to create new projects."
        )

    def test_member_over_plan_limit_gets_permission_message_not_billing(self):
        # A non-admin member in an org that is also at its plan limit must be told they lack
        # permission, not pointed at billing - upgrading the plan cannot unblock them.
        self.organization.available_product_features = []  # no projects feature: capped at the 1 existing project
        self.organization.save()
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

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_member_can_create_project_when_org_allows(self):
        self._set_unlimited_projects()
        self.organization.members_can_create_projects = True
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        with patch("posthog.api.project.create_notification"):
            response = self.client.post("/api/projects/", {"name": "Member Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @override_settings(CLOUD_DEPLOYMENT="US")
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

    @override_settings(CLOUD_DEPLOYMENT="US")
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
    @override_settings(CLOUD_DEPLOYMENT="US")
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
    @override_settings(CLOUD_DEPLOYMENT="US")
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
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_admin_project_creation_does_not_notify(self, mock_create_notification):
        self._set_unlimited_projects()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Admin Project"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_create_notification.assert_not_called()

    @patch("posthog.models.organization.Organization.teams")
    @override_settings(CLOUD_DEPLOYMENT="US")
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

        # Mock the teams queryset to return a count of 2000 non-demo projects
        mock_qs = MagicMock()
        mock_qs.exclude.return_value.distinct.return_value.count.return_value = 2000
        mock_teams.return_value = mock_qs
        mock_teams.exclude.return_value.distinct.return_value.count.return_value = 2000

        # Should not be able to create another project
        response = self.client.post("/api/projects/", {"name": "Project 1001"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response.json()["detail"],
            "You have reached the maximum limit of 2000 projects per organization. Contact support if you'd like access to more projects.",
        )

    @override_settings(CLOUD_DEPLOYMENT="US")
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

    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_deletion_queues_async_task(self, mock_delete_task):
        """Verify that project deletion queues async task for full deletion."""
        self._mark_project_ingested()
        viewset = ProjectViewSet()
        factory = APIRequestFactory()
        request = factory.delete("/fake")
        request.user = self.user
        viewset.request = request

        project_id = self.project.id
        project_name = self.project.name
        team_id = self.team.id

        viewset.perform_destroy(self.project)

        # Project deletion happens async in the Temporal workflow

        mock_delete_task.assert_called_once()
        call_kwargs = mock_delete_task.call_args.kwargs
        self.assertEqual(call_kwargs["team_ids"], [team_id])
        self.assertEqual(call_kwargs["project_id"], project_id)
        self.assertEqual(call_kwargs["user_id"], self.user.id)
        self.assertEqual(call_kwargs["project_name"], project_name)
        self.assertGreater(call_kwargs["start_delay"], timedelta(hours=47))
        self.assertLessEqual(call_kwargs["start_delay"], timedelta(hours=48))

    @parameterized.expand(
        [
            ("cloud_last_project_active_sub", True, 1, True, True, status.HTTP_400_BAD_REQUEST),
            ("cloud_last_project_no_sub", True, 1, False, True, status.HTTP_204_NO_CONTENT),
            ("cloud_non_last_project_active_sub", True, 2, True, True, status.HTTP_204_NO_CONTENT),
            ("self_hosted", False, 1, True, True, status.HTTP_204_NO_CONTENT),
            ("cloud_no_license", True, 1, True, None, status.HTTP_204_NO_CONTENT),
        ]
    )
    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
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

    def _mark_project_ingested(self) -> None:
        self.team.ingested_event = True
        self.team.save(update_fields=["ingested_event"])

    @parameterized.expand(
        [
            ("with_ingested_data", True, timedelta(hours=48)),
            ("without_ingested_data", False, None),
        ]
    )
    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_deletion_sets_pending_deletion_flag(
        self, _name, has_ingested_data, expected_delay, mock_delete_task
    ):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        if has_ingested_data:
            self._mark_project_ingested()

        response = self.client.delete(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertAlmostEqual(
            self.project.deletion_scheduled_at.timestamp(),
            (timezone.now() + (expected_delay or timedelta())).timestamp(),
            delta=5,
        )
        mock_delete_task.assert_called_once()
        start_delay = mock_delete_task.call_args.kwargs["start_delay"]
        if expected_delay is None:
            self.assertIsNone(start_delay)
        else:
            self.assertLessEqual(start_delay, expected_delay)
            self.assertGreater(start_delay, expected_delay - timedelta(minutes=1))

    @patch("posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow")
    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_deletion_can_be_canceled(self, mock_delete_task, mock_cancel_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._mark_project_ingested()
        self.client.delete(f"/api/projects/{self.project.id}")

        response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_pending_deletion)
        self.assertIsNone(self.project.deletion_scheduled_at)
        mock_cancel_delete_task.assert_called_once_with(project_id=self.project.id)
        restored_activities = list(
            ActivityLog.objects.filter(
                team_id=self.project.id,
                item_id=str(self.project.id),
                activity="restored",
            )
            .order_by("scope")
            .values_list("scope", flat=True)
        )
        self.assertEqual(restored_activities, ["Project", "Team"])

    @patch("posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow")
    def test_project_deletion_cancellation_rejects_a_stale_schedule(self, mock_cancel_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        stale_scheduled_at = timezone.now() + timedelta(hours=48)
        current_scheduled_at = timezone.now() - timedelta(seconds=1)
        Project.objects.filter(id=self.project.id).update(
            is_pending_deletion=True,
            deletion_scheduled_at=current_scheduled_at,
        )
        self.project.is_pending_deletion = True
        self.project.deletion_scheduled_at = stale_scheduled_at

        with patch.object(ProjectViewSet, "get_object", return_value=self.project):
            response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("can no longer be canceled", response.json()["detail"])
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, current_scheduled_at)
        mock_cancel_delete_task.assert_not_called()

    @patch(
        "posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow",
        side_effect=Exception("temporal unavailable"),
    )
    def test_project_deletion_cancellation_failure_keeps_project_active(self, mock_cancel_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        scheduled_at = timezone.now() + timedelta(hours=48)
        Project.objects.filter(id=self.project.id).update(
            is_pending_deletion=True,
            deletion_scheduled_at=scheduled_at,
        )

        response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("could not be canceled", response.json()["detail"])
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, scheduled_at)
        mock_cancel_delete_task.assert_called_once_with(project_id=self.project.id)
        self.assertFalse(
            ActivityLog.objects.filter(
                team_id=self.project.id,
                item_id=str(self.project.id),
                activity="restored",
            ).exists()
        )

    @patch("posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow")
    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_can_be_deleted_again_after_cancellation(self, mock_start_delete_task, mock_cancel_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._mark_project_ingested()
        self.client.delete(f"/api/projects/{self.project.id}")

        cancel_response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")
        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)

        mock_start_delete_task.reset_mock()
        response = self.client.delete(f"/api/projects/{self.project.id}")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_start_delete_task.assert_called_once()
        mock_cancel_delete_task.assert_called_once_with(project_id=self.project.id)

    @patch("posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow")
    def test_project_member_cannot_cancel_deletion(self, mock_cancel_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        self.project.is_pending_deletion = True
        self.project.deletion_scheduled_at = timezone.now() + timedelta(hours=48)
        self.project.save(update_fields=["is_pending_deletion", "deletion_scheduled_at"])

        response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertIsNotNone(self.project.deletion_scheduled_at)
        mock_cancel_delete_task.assert_not_called()

    @patch("posthog.temporal.delete_teams.dispatch.cancel_delete_project_data_workflow")
    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_deletion_cannot_be_canceled_after_deletion_starts(
        self, mock_start_delete_task, mock_cancel_delete_task
    ):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.client.delete(f"/api/projects/{self.project.id}")
        Project.objects.filter(id=self.project.id).update(deletion_scheduled_at=timezone.now() - timedelta(hours=1))

        response = self.client.post(f"/api/projects/{self.project.id}/cancel-deletion/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already started", response.json()["detail"])
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        mock_cancel_delete_task.assert_not_called()

    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_project_deletion_returns_pending_deletion_in_api(self, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.client.delete(f"/api/projects/{self.project.id}")

        response = self.client.get(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["is_pending_deletion"])

    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    def test_delete_project_already_pending_deletion_returns_400(self, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.project.is_pending_deletion = True
        self.project.save(update_fields=["is_pending_deletion"])

        response = self.client.delete(f"/api/projects/{self.project.id}")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already being deleted", response.json()["detail"])
        mock_delete_task.assert_not_called()

    @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
    @patch("products.managed_warehouse.backend.facade.api.get_team_deletion_block_reason")
    def test_concurrent_project_deletion_cannot_clear_pending_state(self, mock_block_reason, mock_delete_task):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        scheduled_at = timezone.now() + timedelta(hours=48)

        def claim_deletion(*args: object, **kwargs: object) -> None:
            Project.objects.filter(id=self.project.id).update(
                is_pending_deletion=True,
                deletion_scheduled_at=scheduled_at,
            )
            return None

        mock_block_reason.side_effect = claim_deletion

        response = self.client.delete(f"/api/projects/{self.project.id}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already being deleted", response.json()["detail"])
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, scheduled_at)
        mock_delete_task.assert_not_called()

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

    @parameterized.expand(
        [(False, False, False), (True, False, False), (False, True, False), (True, True, False), (False, True, True)]
    )
    def test_conversations_settings_preserve_managed_values(
        self, include_enabled: bool, clear_settings: bool, use_team_serializer: bool
    ) -> None:
        managed = {
            "widget_public_token": "test-server-generated-token",
            "slack_bot_token": "test-server-managed-token",
            "slack_team_id": "test-slack-team",
            "slack_enabled": False,
            "slack_scopes": "test-scope",
            "teams_enabled": False,
            "teams_tenant_id": None,
            "teams_team_id": "test-team",
            "teams_team_name": "Test team",
            "teams_channel_id": "test-channel",
            "teams_channel_name": "Test channel",
            "teams_channels": [],
            "email_enabled": True,
            "github_enabled": True,
            "github_integration_id": 123,
            "github_repos": ["example-org/example-repo"],
        }
        self.team.conversations_enabled = True
        self.team.conversations_settings = {**managed, "widget_color": "#123456"}
        self.team.save()
        payload: dict[str, dict[str, str] | bool | None] = {
            "conversations_settings": None if clear_settings else dict.fromkeys(managed, "test-client-value")
        }
        if include_enabled:
            payload["conversations_enabled"] = True

        if use_team_serializer:
            request = APIRequestFactory().patch("/", payload, format="json")
            request.user = self.user
            TeamSerializer(context={"request": request}).update(self.team, payload)
        else:
            response = self.client.patch(f"/api/projects/{self.project.id}/", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        self.team.refresh_from_db()
        expected = managed if clear_settings else {**managed, "widget_color": "#123456"}
        self.assertEqual(self.team.conversations_settings, expected)

    @parameterized.expand(
        [(TeamSerializer, "null"), (ProjectBackwardCompatSerializer, "null"), (TeamSerializer, "enabled")]
    )
    def test_conversations_settings_clear_rereads_team_before_merging(self, serializer_class: type, mode: str) -> None:
        # A conversations PATCH must read the team row it writes from under the lock, not
        # from the instance the serializer was handed. Otherwise a dedicated integration
        # update that commits between the request's snapshot and the save gets clobbered
        # by the whole-blob write, restoring stale state.
        self.team.conversations_enabled = False
        self.team.conversations_settings = {"widget_color": "#123456"}
        self.team.save()

        def simulate_integration_update(*args: Any, **kwargs: Any) -> Any:
            # Runs when the update path takes its locking re-read: commit the
            # integration change now, so the merge must see it. The null clear
            # keeps only managed keys, so the token and the integration state
            # the integration update just wrote are the ones that must survive.
            # Another admin enables conversations in the same window.
            Team.objects.filter(pk=self.team.pk).update(
                conversations_enabled=True,
                conversations_settings={
                    "widget_color": "#123456",
                    "widget_public_token": "integration-token",
                    "teams_enabled": True,
                },
            )
            return real_select_for_update(*args, **kwargs)

        def simulate_late_integration_update(team: Team, *args: Any, **kwargs: Any) -> None:
            # Runs after this request's locked write commits. The late write must not
            # be reported as this user's setting change.
            latest = Team.objects.only("conversations_settings").get(pk=team.pk).conversations_settings
            Team.objects.filter(pk=team.pk).update(conversations_settings={**latest, "late_key": True})
            real_refresh_from_db(team, *args, **kwargs)

        real_select_for_update = Team.objects.select_for_update
        real_refresh_from_db = Team.refresh_from_db
        if mode == "null":
            payload: dict[str, Any] = {"conversations_settings": None}
        else:
            payload = {"conversations_enabled": True}

        with (
            capture_db_queries() as queries,
            patch("posthog.api.team.report_user_action") as mock_report,
        ):
            with (
                patch.object(Team.objects, "select_for_update", simulate_integration_update),
                patch.object(Team, "refresh_from_db", simulate_late_integration_update),
            ):
                if serializer_class is TeamSerializer:
                    TeamSerializer(context={"request": MagicMock(user=self.user)}).update(self.team, payload)
                else:
                    request = APIRequestFactory().patch("/", payload, format="json")
                    request.user = self.user
                    ProjectBackwardCompatSerializer(context={"request": request, "view": None}).update(
                        self.project, payload
                    )

        self.team.refresh_from_db()
        if mode == "enabled":
            # The enable path finds the token the integration update just wrote, so it
            # keeps that whole blob rather than re-minting.
            expected: dict[str, Any] = {
                "widget_color": "#123456",
                "widget_public_token": "integration-token",
                "teams_enabled": True,
            }
        else:
            expected = {"widget_public_token": "integration-token", "teams_enabled": True}
        self.assertEqual(self.team.conversations_settings, {**expected, "late_key": True})
        self.assertTrue(self.team.conversations_enabled)

        # The blob must be written exactly once by this request, inside the lock. The
        # first captured UPDATE is the simulated integration write; a second one after
        # the lock is released would clobber an integration writer queued on it.
        settings_saves = [
            q
            for q in queries.captured_queries
            if q["sql"].startswith('UPDATE "posthog_team"') and "late_key" not in q["sql"]
        ]
        self.assertEqual(len(settings_saves), 2, [q["sql"][:120] for q in settings_saves])
        self.assertIn("integration-token", settings_saves[0]["sql"])

        # Neither concurrent writer's keys may be reported as this user's setting changes.
        reported = [c.args[2]["setting"] for c in mock_report.call_args_list if c.args[1] == "support setting changed"]
        self.assertEqual(reported, [] if mode == "enabled" else ["widget_color"])

        # The other admin's toggle must not be logged as this user's change.
        logged_fields = [
            change["field"]
            for log in ActivityLog.objects.filter(team_id=self.team.pk, scope="Team")
            for change in (log.detail or {}).get("changes") or []
        ]
        self.assertNotIn("conversations_enabled", logged_fields)

    @parameterized.expand(
        [
            (TeamSerializer, "saved"),
            (ProjectBackwardCompatSerializer, "saved"),
            (TeamSerializer, "save_fails"),
            (ProjectBackwardCompatSerializer, "save_fails"),
        ]
    )
    def test_conversations_patch_with_other_team_fields_saves_the_team_once(
        self, serializer_class: type, outcome: str
    ) -> None:
        self.team.conversations_settings = {"widget_color": "#123456"}
        self.team.capture_console_log_opt_in = False
        self.team.save()
        payload = {"conversations_settings": {"widget_color": "#654321"}, "capture_console_log_opt_in": True}
        request = APIRequestFactory().patch("/", payload, format="json")
        request.user = self.user
        serializer = serializer_class(context={"request": request, "view": None})
        instance = self.team if serializer_class is TeamSerializer else self.project

        real_save = Team.save

        def save_that_fails_on_other_fields(team: Team, *args: Any, **kwargs: Any) -> None:
            if "capture_console_log_opt_in" in (kwargs.get("update_fields") or []):
                raise DatabaseError("simulated failure")
            real_save(team, *args, **kwargs)

        if outcome == "save_fails":
            with (
                patch.object(Team, "save", autospec=True, side_effect=save_that_fails_on_other_fields),
                self.assertRaises(DatabaseError),
            ):
                serializer.update(instance, payload)
            self.team.refresh_from_db()
            self.assertEqual(self.team.conversations_settings, {"widget_color": "#123456"})
            self.assertFalse(self.team.capture_console_log_opt_in)
            return

        with capture_db_queries() as queries:
            serializer.update(instance, payload)
        team_saves = [q["sql"] for q in queries.captured_queries if q["sql"].startswith('UPDATE "posthog_team"')]
        self.assertEqual(len(team_saves), 1, [sql[:120] for sql in team_saves])
        self.team.refresh_from_db()
        self.assertEqual(self.team.conversations_settings, {"widget_color": "#654321"})
        self.assertTrue(self.team.capture_console_log_opt_in)

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

    def _create_searchable_projects(self) -> None:
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

        for name in [
            "Analytics Dashboard",
            "Revenue Tracker",
            "User Analytics",
            "Acme Non-prod",
            "Acme NON PROD Portal",
        ]:
            Project.objects.create_with_team(
                organization=self.organization,
                name=name,
                initiating_user=self.user,
            )

    @parameterized.expand(
        [
            ("term_matching_several", "Analytics", {"Analytics Dashboard", "User Analytics"}),
            ("term_matching_one", "Revenue", {"Revenue Tracker"}),
            ("term_matching_none", "nonexistent", set()),
            # The space is part of the value, so "Acme Non-prod" must not come back
            ("phrase_keeps_its_space", "NON%20PROD", {"Acme NON PROD Portal"}),
            # Quotes carry no meaning, so they only match a name that contains them
            ("quotes_match_literally", "%22NON%20PROD%22", set()),
        ]
    )
    def test_project_name_search_filter(self, _name: str, query: str, expected_names: set[str]) -> None:
        self._create_searchable_projects()

        response = self.client.get(f"/api/projects/?search={query}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual({result["name"] for result in response.json()["results"]}, expected_names)

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
            "flag_evaluations_mode",
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

    def test_flag_evaluations_mode_is_read_only(self):
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=FlagEvaluationsMode.READ_FLAG_EVALUATIONS
        )

        response = self.client.patch(
            f"/api/projects/{self.project.id}/", {"flag_evaluations_mode": FlagEvaluationsMode.EVENTS}
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["flag_evaluations_mode"], FlagEvaluationsMode.READ_FLAG_EVALUATIONS)
        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=self.organization).flag_evaluations_mode,
            FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
        )

    @parameterized.expand(
        [
            (
                "read_flag_evaluations_reads_events",
                FlagEvaluationsMode.READ_FLAG_EVALUATIONS,
                FlagEvaluationsMode.EVENTS,
            ),
            (
                "flag_evaluations_only_keeps_its_mode",
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
                FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY,
            ),
        ]
    )
    def test_flag_evaluations_mode_while_reads_are_forced_to_events(self, _name, stored_mode, expected_mode):
        OrganizationFeatureFlagsConfig.objects.filter(organization=self.organization).update(
            flag_evaluations_mode=stored_mode
        )

        with override_instance_config("FLAG_EVALUATIONS_READS_FORCE_EVENTS", True):
            response = self.client.get(f"/api/projects/{self.project.id}/")

        self.assertEqual(response.json()["flag_evaluations_mode"], expected_mode)
        self.assertEqual(
            OrganizationFeatureFlagsConfig.objects.get(organization=self.organization).flag_evaluations_mode,
            stored_mode,
        )

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

    def test_rename_project_syncs_passthrough_team_name(self):
        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"name": "Renamed project"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        self.project.refresh_from_db()
        self.team.refresh_from_db()
        self.assertEqual(self.project.name, "Renamed project")
        self.assertEqual(self.team.name, "Renamed project")

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_customer_analytics_config_writes_through_to_team(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        definition_response = self.client.post(
            f"/api/projects/{self.project.id}/custom_property_definitions/",
            {"name": "Annual recurring revenue", "display_type": "currency", "is_big_number": True},
            format="json",
        )
        self.assertEqual(definition_response.status_code, status.HTTP_201_CREATED, definition_response.json())
        default_pins = [{"kind": "custom_property", "id": definition_response.json()["id"]}]

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {
                "customer_analytics_config": {
                    "activity_event": "$pageview",
                    "default_pinned_properties": default_pins,
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["customer_analytics_config"]["activity_event"], "$pageview")
        self.assertEqual(
            response.json()["customer_analytics_config"]["default_pinned_properties"],
            default_pins,
        )

        self.team.refresh_from_db()
        self.assertEqual(self.team.customer_analytics_config.activity_event, "$pageview")
        self.assertEqual(self.team.customer_analytics_config.default_pinned_properties, default_pins)

    def test_customer_analytics_default_pins_reject_invalid_references(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        definition_response = self.client.post(
            f"/api/projects/{self.project.id}/custom_property_definitions/",
            {"name": "Annual recurring revenue", "display_type": "currency", "is_big_number": True},
            format="json",
        )
        self.assertEqual(definition_response.status_code, status.HTTP_201_CREATED, definition_response.json())
        reference = {"kind": "custom_property", "id": definition_response.json()["id"]}

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"customer_analytics_config": {"default_pinned_properties": [reference, reference]}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
        self.assertIn("duplicates", response.json()["detail"])

    def test_project_member_cannot_change_customer_analytics_default_pins(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"customer_analytics_config": {"default_pinned_properties": []}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.json())
        config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        config.refresh_from_db()
        self.assertEqual(config.default_pinned_properties, [])

    def test_customer_analytics_config_save_keeps_track_rules_written_meanwhile(self):
        config = get_or_create_team_extension(self.team, TeamCustomerAnalyticsConfig)
        serializer = TeamCustomerAnalyticsConfigSerializer(config, data={"activity_event": "$pageview"}, partial=True)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        enabled_at = timezone.now()
        rules = {**config.account_track_rules, "written": "meanwhile"}
        TeamCustomerAnalyticsConfig.objects.filter(pk=config.pk).update(
            account_track_rules=rules, account_track_rules_enabled_at=enabled_at
        )

        serializer.save()

        config.refresh_from_db()
        self.assertEqual(config.activity_event, "$pageview")
        self.assertEqual((config.account_track_rules, config.account_track_rules_enabled_at), (rules, enabled_at))

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

    def test_experiments_config_precomputation_toggle_stamps_manual_provenance(self):
        # A missing stamp would let the auto-enrollment job override a human's disable
        # on its next run. Other settings must not stamp it.
        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"default_cuped_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        config = TeamExperimentsConfig.objects.get(team_id=self.project.id)
        self.assertIsNone(config.precomputation_enabled_set_by)

        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"experiment_precomputation_enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        config.refresh_from_db()
        self.assertEqual(config.precomputation_enabled_set_by, TeamExperimentsConfig.PrecomputationEnabledSetBy.MANUAL)

    def test_experiments_config_recalculation_times_write_and_clear(self):
        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"experiment_recalculation_times": ["14:00:00", "02:00:00"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        config = TeamExperimentsConfig.objects.get(team_id=self.project.id)
        self.assertEqual(config.experiment_recalculation_times, ["14:00:00", "02:00:00"])

        # Old clients still PATCH the retired experiment_recalculation_time field;
        # it must be ignored, not rejected.
        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"experiment_recalculation_time": "08:00:00"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        config.refresh_from_db()
        self.assertEqual(config.experiment_recalculation_times, ["14:00:00", "02:00:00"])

        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"experiment_recalculation_times": None},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        config.refresh_from_db()
        self.assertIsNone(config.experiment_recalculation_times)

    @parameterized.expand(
        [
            ("not_on_the_hour", ["08:30:00"]),
            ("bad_format", ["8am"]),
            ("hour_out_of_range", ["24:00:00"]),
            ("more_than_two", ["02:00:00", "10:00:00", "18:00:00"]),
            ("duplicate_hours", ["02:00:00", "02:00:00"]),
            ("closer_than_six_hours", ["08:00:00", "09:00:00"]),
            ("closer_than_six_hours_across_midnight", ["23:00:00", "01:00:00"]),
            ("empty_list", []),
        ]
    )
    def test_experiments_config_rejects_invalid_recalculation_times(self, _name, times):
        response = self.client.patch(
            f"/api/projects/{self.project.id}/experiments_config/",
            {"experiment_recalculation_times": times},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_tags_round_trip_and_land_in_the_project_team_namespace(self):
        # `tags` is not a Project column, so it must be pulled out before the serializer's
        # passthrough loop setattr()s everything left in validated_data onto the model.
        response = self.client.patch(
            f"/api/projects/{self.project.id}/",
            {"tags": ["Production", " EU-Region "]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(sorted(response.json()["tags"]), ["eu-region", "production"])

        reread = self.client.get(f"/api/projects/{self.project.id}/")
        self.assertEqual(sorted(reread.json()["tags"]), ["eu-region", "production"])
        self.assertEqual(
            set(Tag.objects.filter(team_id=self.project.id).values_list("name", flat=True)),
            {"eu-region", "production"},
        )

    def test_tags_are_replaced_and_orphaned_tags_removed(self):
        self.client.patch(f"/api/projects/{self.project.id}/", {"tags": ["keep", "drop"]}, format="json")

        response = self.client.patch(f"/api/projects/{self.project.id}/", {"tags": ["keep"]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        self.assertEqual(response.json()["tags"], ["keep"])
        self.assertEqual(set(Tag.objects.filter(team_id=self.project.id).values_list("name", flat=True)), {"keep"})

    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_project_can_be_created_with_tags(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": 2}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post("/api/projects/", {"name": "Tagged", "tags": ["production"]}, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        self.assertEqual(response.json()["tags"], ["production"])

    @parameterized.expand(
        [
            ("all_narrows_to_projects_carrying_every_tag", "production,eu-region", "all", {"both"}),
            ("all_is_the_default_match_mode", "production,eu-region", None, {"both"}),
            ("any_widens_to_projects_carrying_either_tag", "production,us-region", "any", {"both", "us_only"}),
            ("no_match_returns_nothing", "nonexistent", "all", set()),
        ]
    )
    def test_list_filters_projects_by_tags(self, _name, tags_param, match, expected_keys):
        both, _ = Project.objects.create_with_team(
            organization=self.organization, name="Both", initiating_user=self.user
        )
        us_only, _ = Project.objects.create_with_team(
            organization=self.organization, name="US only", initiating_user=self.user
        )
        self.client.patch(f"/api/projects/{both.id}/", {"tags": ["production", "eu-region"]}, format="json")
        self.client.patch(f"/api/projects/{us_only.id}/", {"tags": ["production", "us-region"]}, format="json")
        ids_by_key = {"both": both.id, "us_only": us_only.id}

        query = f"?tags={tags_param}" + (f"&tags_match={match}" if match else "")
        response = self.client.get(f"/api/projects/{query}")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        returned_ids = [project["id"] for project in response.json()["results"]]
        self.assertEqual(len(returned_ids), len(set(returned_ids)), "A project matching several tags was duplicated")
        self.assertEqual(set(returned_ids), {ids_by_key[key] for key in expected_keys})

    def test_list_rows_carry_tags(self):
        self.client.patch(f"/api/projects/{self.project.id}/", {"tags": ["production"]}, format="json")

        response = self.client.get("/api/projects/")

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
        rows = {project["id"]: project["tags"] for project in response.json()["results"]}
        self.assertEqual(rows[self.project.id], ["production"])

    def test_unknown_tags_match_mode_is_rejected(self):
        response = self.client.get("/api/projects/?tags=production&tags_match=either")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_filtering_by_too_many_tags_is_rejected(self):
        # "all" joins once per tag, so an unbounded list would let a caller size the query plan.
        too_many = ",".join(f"tag-{index}" for index in range(MAX_TAGS_PER_FILTER + 1))

        response = self.client.get(f"/api/projects/?tags={too_many}")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())
