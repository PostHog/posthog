from django.test import override_settings
from rest_framework import status

from posthog.models import OrganizationMembership, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.test.base import APIBaseTest

import posthog.api.personal_api_key  # noqa: F401
import posthog.api.organization  # noqa: F401
import posthog.api.annotation  # noqa: F401


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class TestAllActivityLogSignalHandlers(APIBaseTest):
    """Test that all model_activity_signal handlers create ActivityLog entries."""

    def setUp(self):
        super().setUp()
        ActivityLog.objects.all().delete()

        self.user.current_organization = self.organization
        self.user.save()

    def assertActivityLogCreated(self, scope: str, activity: str | None = None):
        """Assert that an ActivityLog entry was created with the given scope."""
        activity_logs = ActivityLog.objects.filter(scope=scope)
        self.assertTrue(
            activity_logs.exists(),
            f"No ActivityLog found for scope '{scope}'. Available scopes: {list(ActivityLog.objects.values_list('scope', flat=True))}",
        )
        if activity:
            activity_logs = activity_logs.filter(activity=activity)
            self.assertTrue(
                activity_logs.exists(), f"No ActivityLog found for scope '{scope}' and activity '{activity}'"
            )

    def test_personal_api_key_activity_logging(self):
        """Test PersonalAPIKey signal handler."""
        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            "/api/personal_api_keys/",
            {
                "label": "Test API Key",
                "scopes": ["action:read", "insight:write"],
                "scoped_organizations": [],
                "scoped_teams": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        # PersonalAPIKey creation shows as "updated" due to non-auto PK
        self.assertActivityLogCreated("PersonalAPIKey")

        api_key_id = response.json()["id"]
        response = self.client.patch(f"/api/personal_api_keys/{api_key_id}/", {"label": "Updated Test API Key"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 2)
        self.assertActivityLogCreated("PersonalAPIKey", "updated")

    def test_organization_activity_logging(self):
        """Test Organization signal handler."""
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        initial_count = ActivityLog.objects.count()

        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/", {"name": "Updated Organization Name"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("Organization", "updated")

    def test_organization_membership_activity_logging(self):
        """Test OrganizationMembership signal handler."""
        new_user = User.objects.create_user(email="newuser@test.com", password="password123", first_name="New User")

        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/members/", {"user": {"email": new_user.email}}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("OrganizationMembership", "created")

    def test_annotation_activity_logging(self):
        """Test Annotation signal handler."""
        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {"content": "Test annotation", "date_marker": "2024-01-01T12:00:00Z", "scope": "project"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("Annotation", "created")

    def test_feature_flag_activity_logging(self):
        """Test FeatureFlag signal handler."""
        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "key": "test-flag",
                "name": "Test Flag",
                "active": True,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("FeatureFlag", "created")

    def test_batch_export_activity_logging(self):
        """Test BatchExport signal handler."""
        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/batch_exports/",
            {
                "name": "Test Export",
                "destination": {
                    "type": "S3",
                    "config": {
                        "bucket_name": "test-bucket",
                        "region": "us-east-1",
                        "prefix": "test-prefix",
                        "aws_access_key_id": "test-key",
                        "aws_secret_access_key": "test-secret",
                    },
                },
                "interval": "hour",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("BatchExport", "created")

    def test_tag_activity_logging(self):
        """Test Tag signal handler."""
        initial_count = ActivityLog.objects.count()

        response = self.client.post(f"/api/projects/{self.team.id}/tags/", {"name": "test-tag"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("Tag", "created")

    def test_tagged_item_activity_logging(self):
        """Test TaggedItem signal handler."""
        tag_response = self.client.post(f"/api/projects/{self.team.id}/tags/", {"name": "test-tag-for-item"})
        self.assertEqual(tag_response.status_code, status.HTTP_201_CREATED)
        tag_id = tag_response.json()["id"]

        dashboard_response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", {"name": "Test Dashboard"})
        self.assertEqual(dashboard_response.status_code, status.HTTP_201_CREATED)
        dashboard_id = dashboard_response.json()["id"]

        initial_count = ActivityLog.objects.count()

        response = self.client.post(
            f"/api/projects/{self.team.id}/tagged_items/", {"tag": tag_id, "dashboard": dashboard_id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.assertEqual(ActivityLog.objects.count(), initial_count + 1)
        self.assertActivityLogCreated("TaggedItem", "created")

    def test_activity_logs_user_context(self):
        """Test that activity logs capture user context correctly."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/annotations/",
            {"content": "Test user context", "date_marker": "2024-01-01T12:00:00Z", "scope": "project"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        new_logs = ActivityLog.objects.filter(scope="Annotation").order_by("-created_at")
        self.assertTrue(new_logs.exists())

        latest_log = new_logs.first()
        assert latest_log is not None
        self.assertEqual(latest_log.user, self.user)
        self.assertEqual(latest_log.organization_id, self.organization.id)
        self.assertEqual(latest_log.team_id, self.team.id)
