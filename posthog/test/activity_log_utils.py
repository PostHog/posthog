"""
ActivityLogTestHelper - Comprehensive test helper for activity logging models.

This module provides a test helper class with methods to create and update all models
covered by the activity logging system.
"""

from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

from django.utils import timezone

from rest_framework import status

from ee.api.test.base import APILicensedTest

if TYPE_CHECKING:
    pass


class ActivityLogTestHelper(APILicensedTest):
    """Helper class for creating and updating models with activity logging."""

    def setUp(self):
        super().setUp()
        # Ensure we have an authenticated user
        from posthog.models import User

        if not hasattr(self, "user") or not self.user:
            self.user = User.objects.create_user(
                email="test@posthog.com", password="testpass123", first_name="Test", last_name="User"
            )
            self.organization.members.add(self.user)
            self.client.force_login(self.user)

    # Cohort
    def create_cohort(self, name: str = "Test Cohort", **kwargs) -> dict[str, Any]:
        """Create a cohort via API."""
        data = {
            "name": name,
            "groups": [
                {"properties": [{"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}]}
            ],
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/cohorts/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_cohort(self, cohort_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a cohort via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/cohorts/{cohort_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # FeatureFlag
    def create_feature_flag(self, key: str = "test-flag", **kwargs) -> dict[str, Any]:
        """Create a feature flag via API."""
        data = {
            "key": key,
            "name": "Test Feature Flag",
            "filters": {"groups": [{"properties": [], "rollout_percentage": 50}]},
            "active": True,
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/feature_flags/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_feature_flag(self, flag_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a feature flag via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{flag_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Person
    def create_person(self, distinct_id: Optional[str] = None, **kwargs) -> dict[str, Any]:
        """Create a person via API."""
        if not distinct_id:
            distinct_id = str(uuid4())
        data = {
            "distinct_ids": [distinct_id],
            "properties": {"email": "person@test.com", **kwargs.get("properties", {})},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/persons/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_person(self, person_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a person via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/persons/{person_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Group
    def create_group(self, group_type_index: int = 0, group_key: Optional[str] = None, **kwargs) -> dict[str, Any]:
        """Create a group via API."""
        # First ensure group type exists
        from posthog.models.group_type_mapping import GroupTypeMapping

        GroupTypeMapping.objects.get_or_create(
            team=self.team, group_type_index=group_type_index, defaults={"group_type": "organization"}
        )

        if not group_key:
            group_key = f"org:{uuid4()}"

        data = {
            "group_type_index": group_type_index,
            "group_key": group_key,
            "properties": {"name": "Test Organization", **kwargs.get("properties", {})},
        }
        response = self.client.post(f"/api/projects/{self.team.id}/groups/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_group(self, group_type_index: int, group_key: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a group via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/groups/{group_type_index}/{group_key}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Insight
    def create_insight(self, name: str = "Test Insight", **kwargs) -> dict[str, Any]:
        """Create an insight via API."""
        data = {
            "name": name,
            "filters": {"events": [{"id": "$pageview"}], "display": "ActionsLineGraph"},
            "description": "Test insight description",
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/insights/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_insight(self, insight_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an insight via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Plugin
    def create_plugin(self, name: str = "Test Plugin", **kwargs) -> dict[str, Any]:
        """Create a plugin via API."""
        data = {
            "name": name,
            "plugin_type": "local",
            "description": "Test plugin",
            "url": "https://github.com/PostHog/posthog-plugin-test",
            **kwargs,
        }
        response = self.client.post("/api/organizations/@current/plugins/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_plugin(self, plugin_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a plugin via API."""
        response = self.client.patch(f"/api/organizations/@current/plugins/{plugin_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # PluginConfig
    def create_plugin_config(self, plugin_id: int, **kwargs) -> dict[str, Any]:
        """Create a plugin config via API."""
        data = {"plugin": plugin_id, "enabled": True, "order": 0, "config": {"key": "value"}, **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/plugin_configs/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_plugin_config(self, config_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a plugin config via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/plugin_configs/{config_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # HogFunction (using Plugin as base)
    def create_hog_function(self, name: str = "Test Hog Function", **kwargs) -> dict[str, Any]:
        """Create a hog function via API."""
        data = {
            "name": name,
            "description": "Test hog function",
            "enabled": True,
            "inputs": {},
            "hog": "export function onEvent(event, { inputs }) { console.log(event) }",
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/hog_functions/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_hog_function(self, function_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a hog function via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/hog_functions/{function_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # EventDefinition
    def create_event_definition(self, name: str = "$pageview", **kwargs) -> dict[str, Any]:
        """Create an event definition via API."""
        data = {"name": name, "description": "Page view event", "tags": [], **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/event_definitions/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_event_definition(self, definition_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an event definition via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/event_definitions/{definition_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # PropertyDefinition
    def create_property_definition(self, name: str = "test_property", **kwargs) -> dict[str, Any]:
        """Create a property definition via API."""
        data = {"name": name, "description": "Test property", "type": "String", **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/property_definitions/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_property_definition(self, definition_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a property definition via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/property_definitions/{definition_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Notebook
    def create_notebook(self, title: str = "Test Notebook", **kwargs) -> dict[str, Any]:
        """Create a notebook via API."""
        data = {
            "title": title,
            "content": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Test content"}]}],
            },
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/notebooks/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_notebook(self, notebook_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a notebook via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/notebooks/{notebook_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Dashboard
    def create_dashboard(self, name: str = "Test Dashboard", **kwargs) -> dict[str, Any]:
        """Create a dashboard via API."""
        data = {"name": name, "description": "Test dashboard", "tags": [], **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/dashboards/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_dashboard(self, dashboard_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a dashboard via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/dashboards/{dashboard_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Replay (SessionRecordingPlaylist)
    def create_session_recording_playlist(self, name: str = "Test Playlist", **kwargs) -> dict[str, Any]:
        """Create a session recording playlist via API."""
        data = {
            "name": name,
            "description": "Test playlist",
            "filters": {
                "session_recording_duration": {"type": "recording", "key": "duration", "value": 60, "operator": "gt"}
            },
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/session_recording_playlists/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_session_recording_playlist(self, playlist_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a session recording playlist via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/session_recording_playlists/{playlist_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Experiment
    def create_experiment(self, name: str = "Test Experiment", **kwargs) -> dict[str, Any]:
        """Create an experiment via API."""
        # Create a feature flag first that's eligible for experiments
        flag_key = f"experiment-{uuid4()}"
        flag = self.create_feature_flag(
            key=flag_key,
            filters={
                "groups": [{"properties": [], "rollout_percentage": 0}, {"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {
                            "key": "control",
                            "name": "Control Group",
                            "rollout_percentage": 50,
                        },
                        {
                            "key": "test",
                            "name": "Test Variant",
                            "rollout_percentage": 50,
                        },
                    ]
                },
            },
        )

        data = {
            "name": name,
            "description": "Test experiment",
            "feature_flag_key": flag["key"],
            "parameters": {
                "minimum_detectable_effect": 1,
                "recommended_sample_size": 1000,
                "recommended_running_time": 14,
            },
            "filters": {"events": [{"id": "$pageview"}], "display": "ActionsLineGraph"},
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiments/", data, format="json")
        if response.status_code != status.HTTP_201_CREATED:
            # Some experiments might fail due to complex validation rules
            # This is expected and we should handle it gracefully in tests
            error_detail = response.json().get("detail", "Unknown error")
            raise AssertionError(f"Experiment creation failed: {error_detail}")
        return response.json()

    def update_experiment(self, experiment_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an experiment via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiments/{experiment_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Survey
    def create_survey(self, name: str = "Test Survey", **kwargs) -> dict[str, Any]:
        """Create a survey via API."""
        data = {
            "name": name,
            "description": "Test survey",
            "type": "popover",
            "questions": [{"type": "open", "question": "What do you think?"}],
            "targeting_flag_filters": {"groups": []},
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/surveys/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_survey(self, survey_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a survey via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/surveys/{survey_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # EarlyAccessFeature
    def create_early_access_feature(self, name: str = "Test Early Access", **kwargs) -> dict[str, Any]:
        """Create an early access feature via API."""
        # Create a feature flag first
        flag = self.create_feature_flag(key=f"early-access-{uuid4()}")

        data = {
            "name": name,
            "description": "Test early access feature",
            "stage": "beta",
            "feature_flag_key": flag["key"],
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/early_access_features/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_early_access_feature(self, feature_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an early access feature via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/early_access_features/{feature_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Comment
    def create_comment(self, content: str = "Test comment", **kwargs) -> dict[str, Any]:
        """Create a comment via API."""
        # Create an insight first to comment on
        insight = self.create_insight()

        data = {"content": content, "scope": "Insight", "item_id": str(insight["id"]), **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/comments/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_comment(self, comment_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a comment via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/comments/{comment_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Team
    def create_team(self, name: str = "Test Team", **kwargs) -> dict[str, Any]:
        """Create a team via API."""
        data = {"name": name, "timezone": "UTC", **kwargs}
        response = self.client.post("/api/projects/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_team(self, team_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a team via API."""
        response = self.client.patch(f"/api/projects/{team_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Organization
    def create_organization(self, name: str = "Test Org", **kwargs) -> dict[str, Any]:
        """Create an organization via API."""
        data = {"name": name, **kwargs}
        response = self.client.post("/api/organizations/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_organization(self, org_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an organization via API."""
        response = self.client.patch(f"/api/organizations/{org_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # OrganizationMembership
    def create_organization_membership(self, email: str = "newmember@test.com", **kwargs) -> dict[str, Any]:
        """Create an organization membership (invite) via API."""
        data = {
            "target_email": email,
            "level": 8,  # Member level
            **kwargs,
        }
        response = self.client.post(f"/api/organizations/{self.organization.id}/invites/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_organization_membership(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an organization membership via API."""
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/members/{user_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def delete_organization_membership(self, user_id: str, org_id: Optional[str] = None) -> None:
        """Delete an organization membership via API."""
        if not org_id:
            org_id = self.organization.id

        response = self.client.delete(f"/api/organizations/{org_id}/members/{user_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def delete_organization_invite(self, invite_id: str, org_id: Optional[str] = None) -> None:
        """Delete an organization invite via API."""
        if not org_id:
            org_id = self.organization.id

        response = self.client.delete(f"/api/organizations/{org_id}/invites/{invite_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # Role
    def create_role(self, name: str = "Test Role", **kwargs) -> dict[str, Any]:
        """Create a role via API."""
        data = {
            "name": name,
            **kwargs,
        }
        response = self.client.post(f"/api/organizations/{self.organization.id}/roles/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_role(self, role_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a role via API."""
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/roles/{role_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # BatchExport
    def create_batch_export(self, name: str = "Test Export", **kwargs) -> dict[str, Any]:
        """Create a batch export via direct model creation (like the original tests)."""
        from posthog.batch_exports.models import BatchExport, BatchExportDestination

        # Create destination first (like the original tests do)
        destination = BatchExportDestination.objects.create(
            type=BatchExportDestination.Destination.HTTP, config={"url": "https://example.com"}
        )

        batch_export = BatchExport.objects.create(
            team=self.team,
            name=name,
            destination=destination,
            interval="hour",
            **kwargs,
        )

        # Return in the same format as API would
        return {
            "id": str(batch_export.id),
            "name": batch_export.name,
            "interval": batch_export.interval,
            "paused": batch_export.paused,
        }

    def update_batch_export(self, export_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a batch export via direct model access (like the original tests)."""
        from posthog.batch_exports.models import BatchExport

        batch_export = BatchExport.objects.get(id=export_id)
        for field, value in updates.items():
            setattr(batch_export, field, value)
        batch_export.save()

        return {
            "id": str(batch_export.id),
            "name": batch_export.name,
            "interval": batch_export.interval,
            "paused": batch_export.paused,
        }

    # Integration
    def create_integration(self, kind: str = "twilio", **kwargs) -> dict[str, Any]:
        """Create an integration via API."""
        if kind == "twilio":
            data = {"kind": "twilio", "config": {"account_sid": "AC123456", "auth_token": "test_auth_token"}, **kwargs}
        else:
            data = {"kind": kind, **kwargs}

        response = self.client.post(f"/api/projects/{self.team.id}/integrations/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    # Annotation
    def create_annotation(self, content: str = "Test annotation", **kwargs) -> dict[str, Any]:
        """Create an annotation via API."""
        data = {"content": content, "date_marker": timezone.now().isoformat(), "scope": "project", **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/annotations/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_annotation(self, annotation_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an annotation via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/annotations/{annotation_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Tag
    def create_tag(self, name: str = "test-tag", **_kwargs) -> dict[str, Any]:
        """Create a tag via API."""
        # Tags are typically created implicitly when tagging items
        # Create an insight and tag it
        insight = self.create_insight()
        updates = {"tags": [name]}
        return self.update_insight(insight["id"], updates)

    # Subscription
    def create_subscription(self, title: str = "Test Subscription", **kwargs) -> dict[str, Any]:
        """Create a subscription via API."""
        # Create a dashboard first
        dashboard = self.create_dashboard()

        data = {
            "dashboard": dashboard["id"],
            "target_type": "email",
            "target_value": "test@example.com",
            "frequency": "weekly",
            "interval": 1,
            "start_date": timezone.now().isoformat(),
            "title": title,
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/subscriptions/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_subscription(self, subscription_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a subscription via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/subscriptions/{subscription_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # AlertConfiguration
    def create_alert_configuration(self, name: str = "Test Alert", **kwargs) -> dict[str, Any]:
        """Create an alert configuration via API."""
        # Create an insight first
        insight = self.create_insight()

        data = {
            "name": name,
            "insight": insight["id"],
            "config": {"type": "TrendsAlertConfig", "series_index": 0},
            "threshold": {"configuration": {"type": "absolute", "bounds": {"lower": 100, "upper": 1000}}},
            "enabled": True,
            "subscribed_users": [self.user.id],  # Subscribe the current test user
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/alerts/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_alert_configuration(self, alert_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an alert configuration via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/alerts/{alert_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # PersonalAPIKey
    def create_personal_api_key(self, label: str = "Test API Key", **kwargs) -> dict[str, Any]:
        """Create a personal API key via API."""
        data = {
            "label": label,
            "scopes": ["*"],  # Default to all permissions
            "scoped_teams": [],  # No team restrictions by default
            "scoped_organizations": [],  # No organization restrictions by default
            **kwargs,
        }
        response = self.client.post("/api/personal_api_keys/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_personal_api_key(self, key_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a personal API key via API."""
        response = self.client.patch(f"/api/personal_api_keys/{key_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # User
    def create_user_via_invite(
        self, email: Optional[str] = None, org_id: Optional[str] = None, **kwargs
    ) -> dict[str, Any]:
        """Create a user by sending an organization invite."""
        if not email:
            email = f"user-{uuid4()}@test.com"

        if not org_id:
            org_id = self.organization.id

        invite_data = {
            "target_email": email,
            "level": kwargs.get("level", 1),  # Member level
            **kwargs,
        }

        response = self.client.post(f"/api/organizations/{org_id}/invites/", invite_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def create_user(self, email: Optional[str] = None, **kwargs) -> dict[str, Any]:
        """Create a user via API (as admin)."""
        if not email:
            email = f"user-{uuid4()}@test.com"

        # Make current user a staff member to create other users
        self.user.is_staff = True
        self.user.save()

        data = {"first_name": "Test", "email": email, **kwargs}
        response = self.client.post(f"/api/organizations/{self.organization.id}/invites/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_user(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Update current user via API."""
        response = self.client.patch("/api/users/@me/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # Action
    def create_action(self, name: str = "Test Action", **kwargs) -> dict[str, Any]:
        """Create an action via API."""
        data = {
            "name": name,
            "description": "Test action",
            "steps": [{"event": "$pageview", "url": "https://example.com", "url_matching": "contains"}],
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/actions/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_action(self, action_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an action via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/actions/{action_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # DataWarehouseSavedQuery
    def create_data_warehouse_saved_query(self, name: str = "Test Query", **kwargs) -> dict[str, Any]:
        """Create a data warehouse saved query via API."""
        data = {"name": name, "query": {"kind": "HogQLQuery", "query": "SELECT event FROM events LIMIT 10"}, **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/warehouse_saved_queries/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_data_warehouse_saved_query(self, query_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a data warehouse saved query via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/{query_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # ErrorTrackingIssue
    def create_error_tracking_issue(self, name: str = "Test Error", **kwargs) -> dict[str, Any]:
        """Create an error tracking issue via API."""
        # Error tracking issues are typically created automatically from ingested errors
        # This is a simplified version for testing
        data = {"name": name, "description": "Test error issue", "status": "active", **kwargs}
        response = self.client.post(f"/api/projects/{self.team.id}/error_tracking/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_error_tracking_issue(self, issue_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an error tracking issue via API."""
        response = self.client.patch(f"/api/projects/{self.team.id}/error_tracking/{issue_id}/", updates, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # UserGroup
    def create_user_group(self, name: str = "Test User Group", **kwargs) -> dict[str, Any]:
        """Create a user group via API."""
        data = {"name": name, "members": [self.user.id], **kwargs}
        response = self.client.post(f"/api/organizations/{self.organization.id}/user_groups/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_user_group(self, group_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a user group via API."""
        response = self.client.patch(
            f"/api/organizations/{self.organization.id}/user_groups/{group_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # ExperimentSavedMetric
    def create_experiment_saved_metric(self, name: str = "Test Metric", **kwargs) -> dict[str, Any]:
        """Create an experiment saved metric via API."""
        data = {
            "name": name,
            "description": "Test saved metric",
            "query": {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]},
            **kwargs,
        }
        response = self.client.post(f"/api/projects/{self.team.id}/experiment_saved_metrics/", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_experiment_saved_metric(self, metric_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an experiment saved metric via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/experiment_saved_metrics/{metric_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    # BatchImport
    def create_batch_import(self, _name: str = "Test Import", **kwargs) -> dict[str, Any]:
        """Create a batch import via API."""
        # Allow import_config to be passed as parameter for testing specific configurations
        if "import_config" in kwargs:
            import_config = kwargs.pop("import_config")
            source = import_config.get("source", {})
            data_format = import_config.get("data_format", {})
            content = data_format.get("content", {})

            data = {
                "source_type": source.get("type", "s3"),
                "content_type": content.get("type", "captured"),
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
                **kwargs,
            }
        else:
            data = {
                "source_type": "s3",
                "content_type": "captured",
                "s3_bucket": "test-bucket",
                "s3_region": "us-east-1",
                "s3_prefix": "data/",
                "access_key": "test-key",
                "secret_key": "test-secret",
                **kwargs,
            }

        response = self.client.post(f"/api/projects/{self.team.id}/managed_migrations", data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.json()

    def update_batch_import(self, import_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a batch import via API."""
        response = self.client.patch(
            f"/api/projects/{self.team.id}/managed_migrations/{import_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def delete_batch_import(self, import_id: str) -> None:
        """Delete a batch import."""
        response = self.client.delete(f"/api/projects/{self.team.id}/managed_migrations/{import_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def delete_batch_export(self, export_id: str) -> None:
        """Delete a batch export."""
        response = self.client.delete(f"/api/projects/{self.team.id}/batch_exports/{export_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    # TaggedItem
    def create_tagged_item(self, tag_name: str, item_type: str, item_id: str) -> dict[str, Any]:
        """Create a tagged item by tagging an existing item."""
        # This is typically done by updating the item with tags
        if item_type == "Insight":
            return self.update_insight(int(item_id), {"tags": [tag_name]})
        elif item_type == "Dashboard":
            return self.update_dashboard(int(item_id), {"tags": [tag_name]})
        # Add more item types as needed
        return {"tag": tag_name, "item_type": item_type, "item_id": item_id}

    # Project (alias for Team in the API)
    def create_project(self, name: str = "Test Project", **kwargs) -> dict[str, Any]:
        """Create a project via API."""
        return self.create_team(name, **kwargs)

    def update_project(self, project_id: int, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a project via API."""
        return self.update_team(project_id, updates)

    def create_external_data_source(self, source_type: str = "Stripe", **kwargs) -> dict[str, Any]:
        """Create an external data source via API."""
        from unittest.mock import patch

        # Mock the Stripe validation to avoid needing real credentials
        with patch("posthog.temporal.data_imports.sources.stripe.stripe.validate_credentials", return_value=True):
            with patch("products.data_warehouse.backend.data_load.service.sync_external_data_job_workflow"):
                data = {
                    "source_type": source_type,
                    "payload": {
                        "stripe_account_id": "acct_test_placeholder",
                        "stripe_secret_key": "test_key_placeholder_not_real",
                        "schemas": [
                            {
                                "name": "Customer",
                                "should_sync": kwargs.get("should_sync", True),
                                "sync_type": kwargs.get("sync_type", "full_refresh"),
                            }
                        ],
                        **kwargs.get("payload", {}),
                    },
                    **{k: v for k, v in kwargs.items() if k not in ["payload", "should_sync", "sync_type"]},
                }
                response = self.client.post(
                    f"/api/environments/{self.team.id}/external_data_sources/", data, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                return response.json()

    def update_external_data_source(self, source_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an external data source via API."""
        response = self.client.patch(
            f"/api/environments/{self.team.id}/external_data_sources/{source_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def delete_external_data_source(self, source_id: str) -> None:
        """Delete an external data source via API."""
        response = self.client.delete(f"/api/environments/{self.team.id}/external_data_sources/{source_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def create_external_data_schema(self, source_id: str, name: str = "test_schema", **kwargs) -> dict[str, Any]:
        """Create an external data schema by updating the source."""
        return self.update_external_data_source(source_id, {"schemas": [{"name": name, **kwargs}]})

    def update_external_data_schema(self, schema_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an external data schema via API."""
        response = self.client.patch(
            f"/api/environments/{self.team.id}/external_data_schemas/{schema_id}/", updates, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()

    def delete_external_data_schema(self, schema_id: str) -> None:
        """Delete an external data schema via API."""
        response = self.client.delete(f"/api/environments/{self.team.id}/external_data_schemas/{schema_id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def get_activity_logs_for_item(self, scope: str, item_id: str) -> list[Any]:
        """Get activity logs for a specific item."""
        from posthog.models.activity_logging.activity_log import ActivityLog

        return list(
            ActivityLog.objects.filter(
                team_id=self.team.id,
                scope=scope,
                item_id=str(item_id),
            ).order_by("-created_at")
        )

    def clear_activity_logs(self) -> None:
        """Clear all activity logs for the test team."""
        from posthog.models.activity_logging.activity_log import ActivityLog

        ActivityLog.objects.filter(team_id=self.team.id).delete()
