from datetime import UTC, datetime, timedelta
from typing import Any

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, QueryMatchingTest
from unittest import mock
from unittest.mock import ANY, MagicMock, call, patch

from django.core.cache import cache
from django.db import OperationalError
from django.http import HttpResponse
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status, test

from posthog.api.team import (
    TEAM_CONFIG_FIELDS_SET,
    TEAM_CONFIG_MEMBER_FIELDS_SET,
    TeamSerializer,
    _default_data_color_theme_id,
    _reset_default_data_color_theme_id_cache,
)
from posthog.constants import AvailableFeature
from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    cached_group_types_for_team,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.product_intent import ProductIntent
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.test.test_utils import create_group_type_mapping_without_created_at
from posthog.utils import get_instance_realm

from products.dashboards.backend.models.dashboard import Dashboard

from ee.models.rbac.access_control import AccessControl


def team_api_test_factory():
    class TestTeamAPI(APIBaseTest, QueryMatchingTest):
        """Tests for /api/environments/."""

        def setUp(self):
            super().setUp()
            OrganizationMembership.objects.filter(pk=self.organization_membership.pk).update(
                level=OrganizationMembership.Level.ADMIN
            )
            self.organization_membership.refresh_from_db()

        def _assert_activity_log(self, expected: list[dict], team_id: int | None = None) -> None:
            if not team_id:
                team_id = self.team.pk

            starting_log_response = self.client.get(f"/api/environments/{team_id}/activity")
            assert starting_log_response.status_code == 200, starting_log_response.json()
            results = starting_log_response.json()["results"]
            for item in results:
                item.pop("id", None)
            assert results == expected

        def _assert_organization_activity_log(self, expected: list[dict]) -> None:
            starting_log_response = self.client.get(f"/api/organizations/{self.organization.pk}/activity")
            assert starting_log_response.status_code == 200, starting_log_response.json()
            results = starting_log_response.json()["results"]
            for item in results:
                item.pop("id", None)
            assert results == expected

        def _assert_activity_log_is_empty(self) -> None:
            self._assert_activity_log([])

        def test_list_teams(self):
            response = self.client.get("/api/environments/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Listing endpoint always uses the simplified serializer
            response_data = response.json()
            self.assertEqual(len(response_data["results"]), 1)
            self.assertEqual(response_data["results"][0]["name"], self.team.name)
            self.assertNotIn("test_account_filters", response_data["results"][0])
            self.assertNotIn("data_attributes", response_data["results"][0])

            # TODO: These assertions will no longer make sense when we fully remove these attributes from the model
            self.assertNotIn("event_names", response_data["results"][0])
            self.assertNotIn("event_properties", response_data["results"][0])
            self.assertNotIn("event_properties_numerical", response_data["results"][0])

        def test_retrieve_team(self):
            response = self.client.get("/api/environments/@current/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], self.team.name)
            self.assertEqual(response_data["timezone"], "UTC")
            self.assertEqual(response_data["is_demo"], False)
            self.assertEqual(response_data["has_group_types"], False)
            self.assertEqual(
                response_data["person_on_events_querying_enabled"],
                get_instance_setting("PERSON_ON_EVENTS_ENABLED") or get_instance_setting("PERSON_ON_EVENTS_V2_ENABLED"),
            )

            # TODO: These assertions will no longer make sense when we fully remove these attributes from the model
            self.assertNotIn("event_names", response_data)
            self.assertNotIn("event_properties", response_data)
            self.assertNotIn("event_properties_numerical", response_data)
            self.assertNotIn("event_names_with_usage", response_data)
            self.assertNotIn("event_properties_with_usage", response_data)

        def test_retrieve_team_has_group_types(self):
            other_team = Team.objects.create(organization=self.organization, project=self.project)

            response = self.client.get("/api/environments/@current/")
            response_data = response.json()

            self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
            self.assertEqual(response_data["has_group_types"], False)
            self.assertEqual(response_data["group_types"], [])

            create_group_type_mapping_without_created_at(
                project=self.project, team=other_team, group_type="person", group_type_index=0
            )
            create_group_type_mapping_without_created_at(
                project=self.project, team=other_team, group_type="thing", group_type_index=2
            )
            create_group_type_mapping_without_created_at(
                project=self.project, team=other_team, group_type="place", group_type_index=1
            )

            # Clear both cache keys so the next request fetches from DB
            cache.delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}")
            cache.delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.team.project_id}")

            response = self.client.get("/api/environments/@current/")
            response_data = response.json()

            self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
            self.assertEqual(response_data["has_group_types"], True)
            self.assertEqual(
                response_data["group_types"],
                [
                    {
                        "group_type": "person",
                        "group_type_index": 0,
                        "name_singular": None,
                        "name_plural": None,
                        "default_columns": None,
                        "detail_dashboard": None,
                        "created_at": None,
                    },
                    {
                        "group_type": "place",
                        "group_type_index": 1,
                        "name_singular": None,
                        "name_plural": None,
                        "default_columns": None,
                        "detail_dashboard": None,
                        "created_at": None,
                    },
                    {
                        "group_type": "thing",
                        "group_type_index": 2,
                        "name_singular": None,
                        "name_plural": None,
                        "default_columns": None,
                        "detail_dashboard": None,
                        "created_at": None,
                    },
                ],
            )

        def test_group_types_graceful_degradation_on_db_failure(self):
            """When the persons DB is unreachable and no stale data exists, the
            endpoint still returns 200 with empty group types rather than a 500."""
            with patch("posthog.models.group_type_mapping.GroupTypeMapping.objects") as mock_objects:
                mock_objects.filter.return_value.order_by.return_value.values.side_effect = OperationalError(
                    "could not connect to server"
                )
                cache.delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}")
                cache.delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.team.project_id}")

                response = self.client.get("/api/environments/@current/")
                response_data = response.json()

                self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
                self.assertEqual(response_data["has_group_types"], False)
                self.assertEqual(response_data["group_types"], [])

        def test_group_types_stale_cache_survives_prolonged_db_outage(self):
            """After the primary 5-minute cache expires during a prolonged DB outage,
            the stale fallback key (24h TTL) keeps serving last known good data."""
            other_team = Team.objects.create(organization=self.organization, project=self.project)
            create_group_type_mapping_without_created_at(
                project=self.project, team=other_team, group_type="company", group_type_index=0
            )

            # First request populates both primary and stale cache
            cache.delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}")
            cache.delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.team.project_id}")
            response = self.client.get("/api/environments/@current/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json()["has_group_types"], True)

            # Simulate prolonged outage: primary cache expired, but stale key remains
            cache.delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.team.project_id}")

            with patch("posthog.models.group_type_mapping.GroupTypeMapping.objects") as mock_objects:
                mock_objects.filter.return_value.order_by.return_value.values.side_effect = OperationalError(
                    "could not connect to server"
                )

                response = self.client.get("/api/environments/@current/")
                response_data = response.json()

                self.assertEqual(response.status_code, status.HTTP_200_OK, response_data)
                self.assertEqual(response_data["has_group_types"], True)
                self.assertEqual(response_data["group_types"][0]["group_type"], "company")

        def test_cant_retrieve_team_from_another_org(self):
            org = Organization.objects.create(name="New Org")
            team = Team.objects.create(organization=org, name="Default project")

            response = self.client.get(f"/api/environments/{team.pk}/")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.json(), self.not_found_response())

        @freeze_time("2022-02-08")
        def test_update_team_timezone(self):
            self._assert_activity_log_is_empty()

            response = self.client.patch("/api/environments/@current/", {"timezone": "Europe/Lisbon"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], self.team.name)
            self.assertEqual(response_data["timezone"], "Europe/Lisbon")

            self.team.refresh_from_db()
            self.assertEqual(self.team.timezone, "Europe/Lisbon")

            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "changed",
                                    "after": "Europe/Lisbon",
                                    "before": "UTC",
                                    "field": "timezone",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        def test_update_test_filter_default_checked(self):
            response = self.client.patch(
                "/api/environments/@current/", {"test_account_filters_default_checked": "true"}
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["test_account_filters_default_checked"], True)

            self.team.refresh_from_db()
            self.assertEqual(self.team.test_account_filters_default_checked, True)

        def test_retrieve_receive_org_level_activity_logs(self):
            response = self.client.get("/api/environments/@current/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["receive_org_level_activity_logs"], False)

        def test_update_receive_org_level_activity_logs(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.patch("/api/environments/@current/", {"receive_org_level_activity_logs": True})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["receive_org_level_activity_logs"], True)

            self.team.refresh_from_db()
            self.assertEqual(self.team.receive_org_level_activity_logs, True)

        def test_update_receive_org_level_activity_logs_requires_admin(self):
            member_user = User.objects.create_user(email="member@posthog.com", password="password", first_name="Member")
            OrganizationMembership.objects.create(
                user=member_user,
                organization=self.organization,
                level=OrganizationMembership.Level.MEMBER,
            )
            self.client.force_login(member_user)

            response = self.client.patch("/api/environments/@current/", {"receive_org_level_activity_logs": True})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertEqual(
                response.json(),
                {
                    "type": "authentication_error",
                    "code": "permission_denied",
                    "detail": "Only organization owners and admins can modify the receive_org_level_activity_logs setting.",
                    "attr": None,
                },
            )

            self.team.refresh_from_db()
            self.assertEqual(self.team.receive_org_level_activity_logs, False)

        def test_update_receive_org_level_activity_logs_allows_admin(self):
            admin_user = User.objects.create_user(email="admin@posthog.com", password="password", first_name="Admin")
            OrganizationMembership.objects.create(
                user=admin_user,
                organization=self.organization,
                level=OrganizationMembership.Level.ADMIN,
            )
            self.client.force_login(admin_user)

            response = self.client.patch("/api/environments/@current/", {"receive_org_level_activity_logs": True})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["receive_org_level_activity_logs"], True)

            self.team.refresh_from_db()
            self.assertEqual(self.team.receive_org_level_activity_logs, True)

        def test_cannot_set_invalid_timezone_for_team(self):
            response = self.client.patch("/api/environments/@current/", {"timezone": "America/I_Dont_Exist"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                {
                    "type": "validation_error",
                    "code": "invalid_choice",
                    "detail": '"America/I_Dont_Exist" is not a valid choice.',
                    "attr": "timezone",
                },
            )

            self.team.refresh_from_db()
            self.assertNotEqual(self.team.timezone, "America/I_Dont_Exist")

        def test_cant_update_team_from_another_org(self):
            org = Organization.objects.create(name="New Org")
            team = Team.objects.create(organization=org, name="Default project")

            response = self.client.patch(f"/api/environments/{team.pk}/", {"timezone": "Africa/Accra"})
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertEqual(response.json(), self.not_found_response())

            team.refresh_from_db()
            self.assertEqual(team.timezone, "UTC")

        def test_renaming_syncs_project_and_passthrough_team_names(self):
            # The Project's name and its passthrough Team's name both represent "the project's name".
            # A rename through either endpoint must update both, or the name reverts on refresh
            # depending on which model the UI reads.
            self.assertEqual(self.team.id, self.project.id)  # the default team is the project's passthrough
            response = self.client.patch(f"/api/environments/{self.team.id}/", {"name": "Renamed project"})
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.team.refresh_from_db()
            self.project.refresh_from_db()
            self.assertEqual(self.team.name, "Renamed project")
            self.assertEqual(self.project.name, "Renamed project")

        def test_filter_permission(self):
            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"test_account_filters": [{"key": "$current_url", "value": "test"}]},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], self.team.name)
            self.assertEqual(
                response_data["test_account_filters"],
                [{"key": "$current_url", "value": "test"}],
            )

        @patch("posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow")
        @patch("posthoganalytics.capture")
        def test_delete_team_own_second(
            self,
            mock_capture: MagicMock,
            mock_start_workflow: MagicMock,
        ):
            # NOTE: the factory-level setUp already bumps to ADMIN (without firing the
            # "membership level changed" event because it uses .update() to bypass signals),
            # so this test no longer needs to bump the level itself. It also no longer asserts
            # the membership-level-changed capture event since the bump now happens before
            # `mock_capture` is patched.
            team: Team = Team.objects.create_with_data(initiating_user=self.user, organization=self.organization)
            team_pk = team.pk
            # create_with_data fires capture events; clear them so we only assert delete-time events
            mock_capture.reset_mock()

            self.assertEqual(Team.objects.filter(organization=self.organization).count(), 2)

            response = self.client.delete(f"/api/environments/{team.id}")

            self.assertEqual(response.status_code, 204)
            # Team deletion happens async in the (mocked) Temporal workflow, so team still exists
            # We only verify the workflow was started correctly
            expected_capture_calls = [
                call(
                    distinct_id=self.user.distinct_id,
                    event="team deleted",
                    properties=mock.ANY,
                    groups=mock.ANY,
                    send_feature_flags=False,
                ),
            ]
            if self.client_class is EnvironmentToProjectRewriteClient:
                expected_capture_calls.append(
                    call(
                        distinct_id=self.user.distinct_id,
                        event="project deleted",
                        properties=mock.ANY,
                        groups=mock.ANY,
                        send_feature_flags=False,
                    )
                )
                mock_start_workflow.assert_called_once_with(
                    team_ids=[team_pk],
                    project_id=team_pk,
                    user_id=self.user.id,
                    project_name="Default project",
                )
            else:
                mock_start_workflow.assert_called_once_with(
                    team_ids=[team_pk],
                    project_id=None,
                    user_id=self.user.id,
                    project_name="Default project",
                )
            assert mock_capture.call_args_list == expected_capture_calls

        @freeze_time("2022-02-08")
        def test_reset_token(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self._assert_activity_log_is_empty()

            self.team.api_token = "xyz"
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/reset_token/")
            response_data = response.json()

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertNotEqual(response_data["api_token"], "xyz")
            self.assertEqual(response_data["api_token"], self.team.api_token)
            self.assertTrue(response_data["api_token"].startswith("phc_"))

            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "changed",
                                    "after": self.team.api_token,
                                    "before": "xyz",
                                    "field": "api_token",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        def test_reset_token_insufficient_privileges(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            self.team.api_token = "xyz"
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/reset_token/")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        @freeze_time("2022-02-08")
        def test_generate_secret_token(self):
            from posthog.models.utils import mask_key_value

            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self._assert_activity_log_is_empty()

            # Ensure there is no secret API token
            self.team.secret_api_token = None
            self.team.secret_api_token_backup = None
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")
            response_data = response.json()

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            new_secret_api_token = self.team.secret_api_token or ""
            self.assertTrue(new_secret_api_token.startswith("phs_"))
            self.assertEqual(response_data["secret_api_token"], new_secret_api_token)
            self.assertIsNone(self.team.secret_api_token_backup)
            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "created",
                                    "after": {
                                        "secret_api_token": mask_key_value(new_secret_api_token),
                                    },
                                    "before": {"secret_api_token": None},
                                    "field": "secret_api_token",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        @freeze_time("2022-02-08")
        def test_rotate_secret_token(self):
            from posthog.models.utils import mask_key_value

            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self._assert_activity_log_is_empty()

            # Set the secret API token
            secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token = secret_api_token
            self.team.secret_api_token_backup = None
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")
            response_data = response.json()

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertNotEqual(response_data["secret_api_token"], secret_api_token)
            self.assertNotEqual(response_data["secret_api_token"], self.team.secret_api_token_backup)
            self.assertEqual(response_data["secret_api_token"], self.team.secret_api_token)
            self.assertTrue(response_data["secret_api_token"].startswith("phs_"))
            # Backup token should now be the old secret API token
            self.assertEqual(response_data["secret_api_token_backup"], secret_api_token)
            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "changed",
                                    "after": {
                                        "secret_api_token": mask_key_value(self.team.secret_api_token),
                                        "secret_api_token_backup": "phs_...F11C",
                                    },
                                    "before": {
                                        "secret_api_token": "phs_...F11C",
                                        "secret_api_token_backup": None,
                                    },
                                    "field": "secret_api_token",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        @freeze_time("2022-02-08")
        def test_rotate_secret_token_overwrites_backup_token(self):
            from posthog.models.utils import mask_key_value

            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self._assert_activity_log_is_empty()

            # Set the secret API token
            secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token = secret_api_token
            self.team.secret_api_token_backup = "phs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")
            response_data = response.json()

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertNotEqual(response_data["secret_api_token"], secret_api_token)
            self.assertEqual(response_data["secret_api_token"], self.team.secret_api_token)
            self.assertTrue(response_data["secret_api_token"].startswith("phs_"))
            # Backup token should now be the old secret API token
            self.assertEqual(response_data["secret_api_token_backup"], secret_api_token)
            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "changed",
                                    "after": {
                                        "secret_api_token": mask_key_value(self.team.secret_api_token),
                                        "secret_api_token_backup": "phs_...F11C",
                                    },
                                    "before": {
                                        "secret_api_token": "phs_...F11C",
                                        "secret_api_token_backup": "phs_...6789",
                                    },
                                    "field": "secret_api_token",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        @patch("posthog.api.team.posthoganalytics.feature_enabled", return_value=True)
        def test_generate_first_secret_token_blocked_when_psak_enabled(self, _mock_flag):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self.team.secret_api_token = None
            self.team.secret_api_token_backup = None
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("project secret API key", response.json()["detail"])
            self.assertIsNone(self.team.secret_api_token)

        @patch("posthog.api.team.posthoganalytics.feature_enabled", return_value=True)
        def test_rotate_existing_secret_token_allowed_when_psak_enabled(self, _mock_flag):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token = secret_api_token
            self.team.secret_api_token_backup = None
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertNotEqual(self.team.secret_api_token, secret_api_token)
            self.assertEqual(self.team.secret_api_token_backup, secret_api_token)

        @freeze_time("2022-02-08")
        def test_delete_secret_backup_token(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            self._assert_activity_log_is_empty()

            # Set the secret API token
            self.team.secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token_backup = "phs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/delete_secret_token_backup/")
            response_data = response.json()

            self.team.refresh_from_db()
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response_data["secret_api_token"], "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C")
            self.assertIsNone(response_data["secret_api_token_backup"])
            self.assertIsNone(self.team.secret_api_token_backup)
            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "deleted",
                                    "after": None,
                                    "before": "phs_...6789",
                                    "field": "secret_api_token_backup",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        def test_rotate_secret_token_insufficient_privileges(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            self.team.secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token_backup = None
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/rotate_secret_token/")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            # Make sure it's unchanged
            self.assertEqual(self.team.secret_api_token, "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C")
            self.assertIsNone(self.team.secret_api_token_backup)

        def test_delete_secret_token_backup_insufficient_privileges(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            self.team.secret_api_token = "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C"
            self.team.secret_api_token_backup = "phs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            self.team.save()

            response = self.client.patch(f"/api/environments/{self.team.id}/delete_secret_token_backup/")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            # Make sure it's unchanged
            self.assertEqual(self.team.secret_api_token, "phs_JVRb8fNi0XyIKGgUCyi29ZJUOXEr6NF2dKBy5Ws8XVeF11C")
            self.assertEqual(self.team.secret_api_token_backup, "phs_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

        def test_update_primary_dashboard(self):
            d = Dashboard.objects.create(name="Test", team=self.team)

            # Can set it
            response = self.client.patch("/api/environments/@current/", {"primary_dashboard": d.id})
            response_data = response.json()

            self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())
            self.assertEqual(response_data["name"], self.team.name)
            self.assertEqual(response_data["primary_dashboard"], d.id)

        def test_cant_set_primary_dashboard_to_another_teams_dashboard(self):
            self.team.primary_dashboard_id = None  # Remove the default primary dashboard from the picture
            self.team.save()

            team_2 = Team.objects.create(organization=self.organization, name="Default project")
            d = Dashboard.objects.create(name="Test", team=team_2)

            response = self.client.patch("/api/environments/@current/", {"primary_dashboard": d.id})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(
                response.json(),
                self.validation_error_response("Dashboard does not belong to this team.", attr="primary_dashboard"),
            )

        def test_is_generating_demo_data(self):
            cache_key = f"is_generating_demo_data_{self.team.pk}"
            cache.set(cache_key, "True")
            response = self.client.get(f"/api/environments/{self.team.id}/is_generating_demo_data/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"is_generating_demo_data": True})
            cache.delete(cache_key)
            response = self.client.get(f"/api/environments/{self.team.id}/is_generating_demo_data/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.json(), {"is_generating_demo_data": False})

        @freeze_time("2022-02-08")
        def test_team_float_config_can_be_serialized_to_activity_log(self):
            # regression test since this isn't true by default
            response = self.client.patch(f"/api/environments/@current/", {"session_recording_sample_rate": 0.4})
            assert response.status_code == status.HTTP_200_OK
            self._assert_activity_log(
                [
                    {
                        "activity": "updated",
                        "created_at": "2022-02-08T00:00:00Z",
                        "detail": {
                            "changes": [
                                {
                                    "action": "created",
                                    "after": "0.4",
                                    "before": None,
                                    "field": "session_recording_sample_rate",
                                    "type": "Team",
                                },
                            ],
                            "name": "Default project",
                            "short_id": None,
                            "trigger": None,
                            "type": None,
                        },
                        "item_id": str(self.team.pk),
                        "scope": "Team",
                        "user": {
                            "email": "user1@posthog.com",
                            "first_name": "",
                        },
                    },
                ]
            )

        def test_turn_on_exception_autocapture(self):
            response = self.client.get("/api/environments/@current/")
            assert response.json()["autocapture_exceptions_opt_in"] is None

            response = self.client.patch(
                "/api/environments/@current/",
                {"autocapture_exceptions_opt_in": "Welwyn Garden City"},
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json()["detail"] == "Must be a valid boolean."

            response = self.client.patch("/api/environments/@current/", {"autocapture_exceptions_opt_in": True})
            assert response.status_code == status.HTTP_200_OK
            response = self.client.get("/api/environments/@current/")
            assert response.json()["autocapture_exceptions_opt_in"] is True

        def test_configure_exception_autocapture_event_dropping(self):
            response = self.client.get("/api/environments/@current/")
            assert response.json()["autocapture_exceptions_errors_to_ignore"] is None

            response = self.client.patch(
                "/api/environments/@current/",
                {"autocapture_exceptions_errors_to_ignore": {"wat": "am i"}},
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                response.json()["detail"] == "Must provide a list for field: autocapture_exceptions_errors_to_ignore."
            )

            response = self.client.patch(
                "/api/environments/@current/",
                {"autocapture_exceptions_errors_to_ignore": [1, False]},
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                response.json()["detail"]
                == "Must provide a list of strings to field: autocapture_exceptions_errors_to_ignore."
            )

            response = self.client.patch(
                "/api/environments/@current/",
                {"autocapture_exceptions_errors_to_ignore": ["wat am i"]},
            )
            assert response.status_code == status.HTTP_200_OK
            response = self.client.get("/api/environments/@current/")
            assert response.json()["autocapture_exceptions_errors_to_ignore"] == ["wat am i"]

        def test_configure_exception_autocapture_event_dropping_only_allows_simple_config(self):
            response = self.client.patch(
                "/api/environments/@current/",
                {"autocapture_exceptions_errors_to_ignore": ["abc" * 300]},
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                response.json()["detail"]
                == "Field autocapture_exceptions_errors_to_ignore must be less than 300 characters. Complex config should be provided in posthog-js initialization."
            )

        def test_invalid_session_recording_config_returns_validation_error_envelope(self) -> None:
            # Smoke test that bad config is rejected through the endpoint with the rendered
            # `{attr, code, detail, type}` envelope (note `invalid` is rendered as `invalid_input`).
            # The per-field/per-value matrix lives in TestTeamSerializerValidationNoDB, which
            # exercises the same TeamSerializer validators without a database.
            # Use a non-numeric value so DRF raises the raw `invalid` code — this is the case that
            # exercises exceptions-hog rendering it as `invalid_input`. A numeric out-of-range value
            # yields `max_value`, which is passed through unchanged and would not guard the rename.
            response = self.client.patch(
                "/api/environments/@current/", {"session_recording_sample_rate": "Welwyn Garden City"}
            )
            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert response.json() == {
                "attr": "session_recording_sample_rate",
                "code": "invalid_input",
                "detail": "A valid number is required.",
                "type": "validation_error",
            }

        def test_can_set_and_unset_session_recording_linked_flag(self) -> None:
            self._patch_linked_flag_config({"id": 1, "key": "provided_value"})
            self._assert_linked_flag_config({"id": 1, "key": "provided_value"})

            self._patch_linked_flag_config(None)
            self._assert_linked_flag_config(None)

        def test_can_set_and_unset_session_recording_linked_flag_variant(self) -> None:
            self._patch_linked_flag_config({"id": 1, "key": "provided_value", "variant": "test"})
            self._assert_linked_flag_config({"id": 1, "key": "provided_value", "variant": "test"})

            self._patch_linked_flag_config(None)
            self._assert_linked_flag_config(None)

        def test_can_set_and_unset_session_recording_network_payload_capture_config(self) -> None:
            # can set just one
            first_patch_response = self.client.patch(
                "/api/environments/@current/",
                {"session_recording_network_payload_capture_config": {"recordHeaders": True}},
            )
            assert first_patch_response.status_code == status.HTTP_200_OK
            get_response = self.client.get("/api/environments/@current/")
            assert get_response.json()["session_recording_network_payload_capture_config"] == {"recordHeaders": True}

            # can set the other
            first_patch_response = self.client.patch(
                "/api/environments/@current/",
                {"session_recording_network_payload_capture_config": {"recordBody": False}},
            )
            assert first_patch_response.status_code == status.HTTP_200_OK
            get_response = self.client.get("/api/environments/@current/")
            assert get_response.json()["session_recording_network_payload_capture_config"] == {"recordBody": False}

            # can unset both
            response = self.client.patch(
                "/api/environments/@current/", {"session_recording_network_payload_capture_config": None}
            )
            assert response.status_code == status.HTTP_200_OK
            second_get_response = self.client.get("/api/environments/@current/")
            assert second_get_response.json()["session_recording_network_payload_capture_config"] is None

        def test_can_set_and_unset_survey_settings(self):
            survey_appearance = {
                "thankYouMessageHeader": "Thanks for your feedback!",
                "thankYouMessageDescription": "We'll use it to make notebooks better",
                "backgroundColor": "#ffcc99",
            }

            self._patch_config("survey_config", {"appearance": survey_appearance})
            self._assert_surveys_config_is({"appearance": survey_appearance})

            survey_appearance["zIndex"] = "100001"
            self._patch_config("survey_config", {"appearance": survey_appearance})
            self._assert_surveys_config_is({"appearance": survey_appearance})

            survey_appearance["thankYouMessageHeader"] = "Thanks!"
            self._patch_config("survey_config", {"appearance": survey_appearance})
            self._assert_surveys_config_is({"appearance": survey_appearance})

            self._patch_config("survey_config", None)
            self._assert_replay_config_is(None)

        def test_can_set_and_unset_session_replay_config(self) -> None:
            # can set
            self._patch_session_replay_config({"record_canvas": True})
            self._assert_replay_config_is({"record_canvas": True})

            # can unset
            self._patch_session_replay_config(None)
            self._assert_replay_config_is(None)

        def test_can_set_and_unset_session_replay_config_ai_config(self) -> None:
            # can set just the opt-in
            self._patch_session_replay_config({"ai_config": {"opt_in": True}})
            self._assert_replay_config_is({"ai_config": {"opt_in": True}})

            # can set some preferences
            self._patch_session_replay_config(
                {"ai_config": {"opt_in": False, "included_event_properties": ["something"]}}
            )
            self._assert_replay_config_is({"ai_config": {"opt_in": False, "included_event_properties": ["something"]}})

            self._patch_session_replay_config({"ai_config": None})
            self._assert_replay_config_is({"ai_config": None})

        def test_can_set_replay_configs_without_providing_them_all(self) -> None:
            # can set just the opt-in
            self._patch_session_replay_config({"ai_config": {"opt_in": True}})
            self._assert_replay_config_is({"ai_config": {"opt_in": True}})

            self._patch_session_replay_config({"record_canvas": True})
            self._assert_replay_config_is({"record_canvas": True, "ai_config": {"opt_in": True}})

        def test_can_set_replay_configs_without_providing_them_all_even_when_either_side_is_none(self) -> None:
            # because we do some dictionary copying we need a regression test to ensure we can always set and unset keys
            self._patch_session_replay_config({"record_canvas": True, "ai_config": {"opt_in": True}})
            self._assert_replay_config_is({"record_canvas": True, "ai_config": {"opt_in": True}})

            self._patch_session_replay_config({"record_canvas": None})
            self._assert_replay_config_is({"record_canvas": None, "ai_config": {"opt_in": True}})

            # top-level from having a value to None
            self._patch_session_replay_config(None)
            self._assert_replay_config_is(None)

            # top-level from None to having a value
            self._patch_session_replay_config({"ai_config": None})
            self._assert_replay_config_is({"ai_config": None})

            # next-level from None to having a value
            self._patch_session_replay_config({"ai_config": {"opt_in": True}})
            self._assert_replay_config_is({"ai_config": {"opt_in": True}})

            # next-level from having a value to None
            self._patch_session_replay_config({"ai_config": None})
            self._assert_replay_config_is({"ai_config": None})

        def test_can_set_replay_configs_patch_session_replay_config_one_level_deep(self) -> None:
            # can set just the opt-in
            self._patch_session_replay_config({"ai_config": {"opt_in": True}})
            self._assert_replay_config_is({"ai_config": {"opt_in": True}})

            self._patch_session_replay_config({"ai_config": {"included_event_properties": ["something"]}})
            # even though opt_in was not provided in the patch it should be preserved
            self._assert_replay_config_is({"ai_config": {"opt_in": True, "included_event_properties": ["something"]}})

            self._patch_session_replay_config(
                {"ai_config": {"opt_in": None, "included_event_properties": ["something"]}}
            )
            # even though opt_in was not provided in the patch it should be preserved
            self._assert_replay_config_is({"ai_config": {"opt_in": None, "included_event_properties": ["something"]}})

            # but we don't go into the next nested level and patch that data
            # sending a new value without the original
            self._patch_session_replay_config({"ai_config": {"included_event_properties": ["and another"]}})
            # and the existing second level nesting is not preserved
            self._assert_replay_config_is({"ai_config": {"opt_in": None, "included_event_properties": ["and another"]}})

        def test_modifiers_are_merged_on_patch(self) -> None:
            # Set initial modifiers with personsOnEventsMode
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {"modifiers": {"personsOnEventsMode": "person_id_override_properties_on_events"}},
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["modifiers"] == {"personsOnEventsMode": "person_id_override_properties_on_events"}

            # Patch with customChannelTypeRules - should preserve personsOnEventsMode
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {
                    "modifiers": {
                        "customChannelTypeRules": [
                            {"id": "test", "channel_type": "Direct", "combiner": "AND", "items": []}
                        ]
                    }
                },
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["modifiers"]["personsOnEventsMode"] == "person_id_override_properties_on_events"
            assert response.json()["modifiers"]["customChannelTypeRules"] == [
                {"id": "test", "channel_type": "Direct", "combiner": "AND", "items": []}
            ]

            # Patch with a different personsOnEventsMode - should update it while keeping customChannelTypeRules
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {"modifiers": {"personsOnEventsMode": "person_id_override_properties_joined"}},
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["modifiers"]["personsOnEventsMode"] == "person_id_override_properties_joined"
            assert response.json()["modifiers"]["customChannelTypeRules"] == [
                {"id": "test", "channel_type": "Direct", "combiner": "AND", "items": []}
            ]

        @parameterized.expand(
            [
                (1, True),
                (-1, False),
                (60, True),
                (120, True),
                (1.5, True),
                (None, True),
                (0, False),
                (121, False),
                (999999999, False),
                ("not-a-number", False),
            ]
        )
        def test_modifiers_bounceRateDurationSeconds_validation(self, value: Any, should_succeed: bool) -> None:
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {"modifiers": {"bounceRateDurationSeconds": value}},
            )

            if should_succeed:
                assert response.status_code == status.HTTP_200_OK, response.json()
                assert response.json()["modifiers"]["bounceRateDurationSeconds"] == value
            else:
                assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

        def test_modifiers_rejects_nested_objects(self) -> None:
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {"modifiers": {"bounceRateDurationSeconds": {"nested": "object"}}},
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

        def test_modifiers_rejects_unknown_keys(self) -> None:
            response = self.client.patch(
                f"/api/environments/{self.team.id}",
                {"modifiers": {"unknownField": True}},
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST

        @patch("posthog.event_usage.report_user_action")
        @freeze_time("2024-01-01T00:00:00Z")
        def test_can_add_product_intent(self, mock_report_user_action: MagicMock) -> None:
            response = self.client.patch(
                f"/api/environments/{self.team.id}/add_product_intent/",
                {"product_type": "product_analytics", "intent_context": "onboarding product selected - primary"},
                headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
            )
            assert response.status_code == status.HTTP_201_CREATED
            product_intent = ProductIntent.objects.get(team=self.team, product_type="product_analytics")
            assert product_intent.created_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            assert product_intent.onboarding_completed_at is None
            mock_report_user_action.assert_called_once_with(
                self.user,
                "user showed product intent",
                {
                    "product_key": "product_analytics",
                    "$current_url": "https://posthogtest.com/my-url",
                    "$session_id": "test_session_id",
                    "$set_once": {},
                    "intent_context": "onboarding product selected - primary",
                    "is_first_intent_for_product": True,
                    "intent_created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                    "intent_updated_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                    "realm": get_instance_realm(),
                },
                team=self.team,
            )

        @patch("posthog.api.team.enqueue_product_activation_calc_debounced", MagicMock())
        @patch("posthog.models.product_intent.ProductIntent.check_and_update_activation", return_value=False)
        @patch("posthog.event_usage.report_user_action")
        @freeze_time("2024-01-01T00:00:00Z")
        def test_can_update_product_intent_if_already_exists(
            self,
            mock_report_user_action: MagicMock,
            mock_check_and_update_activation: MagicMock,
        ) -> None:
            """
            Intent already exists, but hasn't been activated yet. It should update the intent
            and send a new event for the user showing the intent.
            """
            intent = ProductIntent.objects.create(team=self.team, product_type="product_analytics")
            original_created_at = intent.created_at
            assert original_created_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            # change the time of the existing intent
            with freeze_time("2024-01-02T00:00:00Z"):
                response = self.client.patch(
                    f"/api/environments/{self.team.id}/add_product_intent/",
                    {"product_type": "product_analytics"},
                    headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
                )
                assert response.status_code == status.HTTP_201_CREATED
                product_intent = ProductIntent.objects.get(team=self.team, product_type="product_analytics")
                assert product_intent.updated_at == datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC)
                assert product_intent.created_at == original_created_at
                assert product_intent.onboarding_completed_at is None
                mock_check_and_update_activation.assert_called_once()
                mock_report_user_action.assert_called_once_with(
                    self.user,
                    "user showed product intent",
                    {
                        "product_key": "product_analytics",
                        "$current_url": "https://posthogtest.com/my-url",
                        "$session_id": "test_session_id",
                        "$set_once": {},
                        "intent_context": None,
                        "is_first_intent_for_product": False,
                        "intent_created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                        "intent_updated_at": datetime(2024, 1, 2, 0, 0, 0, tzinfo=UTC),
                        "realm": get_instance_realm(),
                    },
                    team=self.team,
                )

        @patch("posthog.api.project.report_user_action")
        @patch("posthog.api.team.report_user_action")
        def test_can_complete_product_onboarding(
            self, mock_report_user_action: MagicMock, mock_report_user_action_legacy_endpoint: MagicMock
        ) -> None:
            if self.client_class is EnvironmentToProjectRewriteClient:
                mock_report_user_action = mock_report_user_action_legacy_endpoint
            with freeze_time("2024-01-01T00:00:00Z"):
                product_intent = ProductIntent.objects.create(team=self.team, product_type="product_analytics")
            assert product_intent.created_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            assert product_intent.onboarding_completed_at is None
            with freeze_time("2024-01-05T00:00:00Z"):
                response = self.client.patch(
                    f"/api/environments/{self.team.id}/complete_product_onboarding/",
                    {"product_type": "product_analytics"},
                    headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
                )
            assert response.status_code == status.HTTP_200_OK
            product_intent = ProductIntent.objects.get(team=self.team, product_type="product_analytics")
            assert product_intent.onboarding_completed_at == datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
            mock_report_user_action.assert_called_once_with(
                self.user,
                "product onboarding completed",
                {
                    "product_key": "product_analytics",
                    "intent_context": None,
                    "intent_created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                    "intent_updated_at": datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC),
                    "realm": get_instance_realm(),
                },
                team=self.team,
                request=ANY,
            )

        @patch("posthog.api.project.report_user_action")
        @patch("posthog.api.team.report_user_action")
        def test_can_complete_product_onboarding_as_member(
            self, mock_report_user_action: MagicMock, mock_report_user_action_legacy_endpoint: MagicMock
        ) -> None:
            from ee.models.rbac.access_control import AccessControl

            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()

            # Set up new access control system - restrict project to no default access
            AccessControl.objects.create(
                team=self.team,
                access_level="none",
                resource="project",
                resource_id=str(self.team.id),
            )
            # Grant specific member access to this user
            AccessControl.objects.create(
                team=self.team,
                access_level="member",
                resource="project",
                resource_id=str(self.team.id),
                organization_member=self.organization_membership,
            )

            if self.client_class is EnvironmentToProjectRewriteClient:
                mock_report_user_action = mock_report_user_action_legacy_endpoint
            with freeze_time("2024-01-01T00:00:00Z"):
                product_intent = ProductIntent.objects.create(team=self.team, product_type="product_analytics")
            assert product_intent.created_at == datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
            assert product_intent.onboarding_completed_at is None
            with freeze_time("2024-01-05T00:00:00Z"):
                response = self.client.patch(
                    f"/api/environments/{self.team.id}/complete_product_onboarding/",
                    {"product_type": "product_analytics"},
                    headers={"Referer": "https://posthogtest.com/my-url", "X-Posthog-Session-Id": "test_session_id"},
                )
            assert response.status_code == status.HTTP_200_OK
            product_intent = ProductIntent.objects.get(team=self.team, product_type="product_analytics")
            assert product_intent.onboarding_completed_at == datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC)
            mock_report_user_action.assert_called_once_with(
                self.user,
                "product onboarding completed",
                {
                    "product_key": "product_analytics",
                    "intent_context": None,
                    "intent_created_at": datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC),
                    "intent_updated_at": datetime(2024, 1, 5, 0, 0, 0, tzinfo=UTC),
                    "realm": get_instance_realm(),
                },
                team=self.team,
                request=ANY,
            )

        def _create_other_org_and_team(
            self, membership_level: OrganizationMembership.Level = OrganizationMembership.Level.ADMIN
        ):
            other_org, other_org_membership, _ = Organization.objects.bootstrap(self.user)
            if not other_org_membership:
                raise Exception("Failed to create other org and team")
            other_org_membership.level = membership_level
            other_org_membership.save()
            return other_org, other_org_membership

        def test_cant_change_organization_if_not_admin_of_target_org(self):
            other_org, _ = self._create_other_org_and_team(OrganizationMembership.Level.MEMBER)
            res = self.client.post(
                f"/api/projects/{self.team.project.id}/change_organization/", {"organization_id": other_org.id}
            )

            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                res.json()["detail"]
                == "You must be an admin of both the source and target organizations to move a project."
            )

        def test_cant_change_organization_if_not_admin_of_source_org(self):
            other_org, _ = self._create_other_org_and_team(OrganizationMembership.Level.OWNER)
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            res = self.client.post(
                f"/api/projects/{self.team.project.id}/change_organization/", {"organization_id": other_org.id}
            )

            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert (
                res.json()["detail"]
                == "You must be an admin of both the source and target organizations to move a project."
            )

        def test_can_change_organization(self):
            other_org, _ = self._create_other_org_and_team(OrganizationMembership.Level.ADMIN)
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            res = self.client.post(
                f"/api/projects/{self.team.project.id}/change_organization/", {"organization_id": other_org.id}
            )

            assert res.status_code == status.HTTP_200_OK, res.json()
            assert res.json()["id"] == self.team.id
            assert res.json()["organization"] == str(other_org.id)
            self.project.refresh_from_db()
            self.team.refresh_from_db()
            assert self.project.organization == other_org
            assert self.team.organization == other_org

        def _assert_replay_config_is(self, expected: dict[str, Any] | None) -> HttpResponse:
            return self._assert_config_is("session_replay_config", expected)

        def _assert_surveys_config_is(self, expected: dict[str, Any] | None) -> HttpResponse:
            return self._assert_config_is("survey_config", expected)

        def _assert_config_is(self, config_name, expected: dict[str, Any] | None) -> HttpResponse:
            get_response = self.client.get("/api/environments/@current/")
            assert get_response.status_code == status.HTTP_200_OK, get_response.json()
            assert get_response.json()[config_name] == expected

            return get_response

        def _patch_config(
            self, config_name, config: dict[str, Any] | None, expected_status: int = status.HTTP_200_OK
        ) -> HttpResponse:
            patch_response = self.client.patch(
                "/api/environments/@current/",
                {config_name: config},
            )
            assert patch_response.status_code == expected_status, patch_response.json()

            return patch_response

        def _patch_session_replay_config(
            self, config: dict[str, Any] | None, expected_status: int = status.HTTP_200_OK
        ) -> HttpResponse:
            return self._patch_config("session_replay_config", config, expected_status)

        def _assert_linked_flag_config(self, expected_config: dict | None) -> HttpResponse:
            response = self.client.get("/api/environments/@current/")
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_linked_flag"] == expected_config
            return response

        def _patch_linked_flag_config(
            self, config: dict | None, expected_status: int = status.HTTP_200_OK
        ) -> HttpResponse:
            response = self.client.patch("/api/environments/@current/", {"session_recording_linked_flag": config})
            assert response.status_code == expected_status, response.json()
            return response

        @patch("posthoganalytics.capture_exception")
        def test_access_control_field_deprecated_on_update(self, mock_capture_exception):
            """Test that access_control field is deprecated and cannot be used when updating a team."""
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.patch(
                "/api/environments/@current/",
                {"name": "Updated Name", "access_control": False},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            error_data = response.json()
            self.assertIn("deprecated", error_data["detail"])
            self.assertIn("https://posthog.com/docs/settings/access-control", error_data["detail"])

            # Verify that the exception was captured
            mock_capture_exception.assert_called_once()
            call_args = mock_capture_exception.call_args
            self.assertEqual(call_args[0][0].args[0], "Deprecated access control field used")
            self.assertEqual(call_args[1]["properties"]["field"], "access_control")
            self.assertEqual(call_args[1]["properties"]["value"], "False")
            self.assertEqual(call_args[1]["properties"]["user_id"], self.user.id)

        @patch("posthoganalytics.capture_exception")
        def test_access_control_field_deprecated_on_partial_update(self, mock_capture_exception):
            """Test that access_control field is deprecated and cannot be used when partially updating a team."""
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.patch(
                "/api/environments/@current/",
                {"access_control": True},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            error_data = response.json()
            self.assertIn("deprecated", error_data["detail"])
            self.assertIn("https://posthog.com/docs/settings/access-control", error_data["detail"])

            # Verify that the exception was captured
            mock_capture_exception.assert_called_once()
            call_args = mock_capture_exception.call_args
            self.assertEqual(call_args[0][0].args[0], "Deprecated access control field used")
            self.assertEqual(call_args[1]["properties"]["field"], "access_control")
            self.assertEqual(call_args[1]["properties"]["value"], "True")
            self.assertEqual(call_args[1]["properties"]["user_id"], self.user.id)

        @patch("posthoganalytics.capture_exception")
        def test_access_control_field_deprecated_with_other_valid_fields(self, mock_capture_exception):
            """Test that access_control field is deprecated even when other valid fields are provided."""
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()

            response = self.client.patch(
                "/api/environments/@current/",
                {"timezone": "Europe/London", "access_control": True},
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            error_data = response.json()
            self.assertIn("deprecated", error_data["detail"])
            self.assertIn("https://posthog.com/docs/settings/access-control", error_data["detail"])

            # Verify that the exception was captured
            mock_capture_exception.assert_called_once()
            call_args = mock_capture_exception.call_args
            self.assertEqual(call_args[0][0].args[0], "Deprecated access control field used")
            self.assertEqual(call_args[1]["properties"]["field"], "access_control")
            self.assertEqual(call_args[1]["properties"]["value"], "True")
            self.assertEqual(call_args[1]["properties"]["user_id"], self.user.id)

            # Verify that no changes were made to the team
            self.team.refresh_from_db()
            self.assertEqual(self.team.timezone, "UTC")  # Should remain unchanged

        @parameterized.expand(
            [
                (
                    "app_urls_mixed_nulls",
                    "app_urls",
                    ["https://example.com", None, "https://test.com", None],
                    ["https://example.com", "https://test.com"],
                    None,
                ),
                ("app_urls_all_nulls", "app_urls", [None, None, None], [], None),
                (
                    "app_urls_mixed_valid_and_null",
                    "app_urls",
                    ["https://new.com", None, "https://another.com"],
                    ["https://new.com", "https://another.com"],
                    ["https://existing.com"],
                ),
                (
                    "recording_domains_mixed_nulls",
                    "recording_domains",
                    [None, "https://example.com", None, "https://test.com"],
                    ["https://example.com", "https://test.com"],
                    None,
                ),
                ("recording_domains_none_field", "recording_domains", None, None, None),
            ]
        )
        def test_filters_null_values(self, name, field_name, input_data, expected_output, setup_data):
            if setup_data is not None:
                setattr(self.team, field_name, setup_data)
                self.team.save()

            response = self.client.patch("/api/environments/@current/", {field_name: input_data})

            assert response.status_code == status.HTTP_200_OK
            response_data = response.json()

            if expected_output is None:
                assert response_data[field_name] is None
            else:
                assert response_data[field_name] == expected_output

            self.team.refresh_from_db()
            actual_value = getattr(self.team, field_name)

            if expected_output is None:
                assert actual_value is None
            else:
                assert actual_value == expected_output

        def test_conversations_settings_filters_null_widget_domains(self):
            response = self.client.patch(
                "/api/environments/@current/",
                {"conversations_settings": {"widget_domains": ["https://example.com", None, "https://test.com", None]}},
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["conversations_settings"]["widget_domains"] == [
                "https://example.com",
                "https://test.com",
            ]

        def test_conversations_settings_merges_with_existing(self):
            self.client.patch(
                "/api/environments/@current/",
                {"conversations_settings": {"widget_greeting_text": "Hello!"}},
            )
            response = self.client.patch(
                "/api/environments/@current/",
                {"conversations_settings": {"widget_color": "#ff0000"}},
            )
            assert response.status_code == status.HTTP_200_OK
            settings = response.json()["conversations_settings"]
            assert settings["widget_greeting_text"] == "Hello!"
            assert settings["widget_color"] == "#ff0000"

        def test_conversations_widget_position_setting(self):
            response = self.client.patch(
                "/api/environments/@current/",
                {"conversations_settings": {"widget_position": "top_left"}},
            )
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["conversations_settings"]["widget_position"] == "top_left"

        def test_conversations_identification_settings(self):
            response = self.client.patch(
                "/api/environments/@current/",
                {
                    "conversations_settings": {
                        "widget_require_email": True,
                        "widget_collect_name": True,
                        "widget_identification_form_title": "Before we start...",
                        "widget_identification_form_description": "Please provide your details.",
                        "widget_placeholder_text": "Type your message...",
                    }
                },
            )
            assert response.status_code == status.HTTP_200_OK
            settings = response.json()["conversations_settings"]
            assert settings["widget_require_email"] is True
            assert settings["widget_collect_name"] is True
            assert settings["widget_identification_form_title"] == "Before we start..."
            assert settings["widget_identification_form_description"] == "Please provide your details."
            assert settings["widget_placeholder_text"] == "Type your message..."

        def test_enabling_conversations_auto_generates_token(self):
            self.team.conversations_enabled = False
            self.team.conversations_settings = None
            self.team.save()

            response = self.client.patch("/api/environments/@current/", {"conversations_enabled": True})
            assert response.status_code == status.HTTP_200_OK
            settings = response.json()["conversations_settings"]
            assert settings is not None
            assert settings.get("widget_public_token") is not None
            assert len(settings["widget_public_token"]) > 20

        def test_enabling_conversations_preserves_existing_token(self):
            self.team.conversations_enabled = False
            self.team.conversations_settings = {"widget_public_token": "existing_token_123"}
            self.team.save()

            response = self.client.patch("/api/environments/@current/", {"conversations_enabled": True})
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["conversations_settings"]["widget_public_token"] == "existing_token_123"

        def test_disabling_conversations_clears_token(self):
            self.team.conversations_enabled = True
            self.team.conversations_settings = {"widget_public_token": "some_token", "widget_color": "#123456"}
            self.team.save()

            response = self.client.patch("/api/environments/@current/", {"conversations_enabled": False})
            assert response.status_code == status.HTTP_200_OK
            settings = response.json()["conversations_settings"]
            assert settings["widget_public_token"] is None
            assert settings["widget_color"] == "#123456"

        def test_generate_conversations_public_token(self):
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            self.team.conversations_settings = {"widget_color": "#123456"}
            self.team.save()

            response = self.client.post(f"/api/environments/{self.team.id}/generate_conversations_public_token/")
            assert response.status_code == status.HTTP_200_OK
            settings = response.json()["conversations_settings"]
            assert settings["widget_public_token"] is not None
            assert len(settings["widget_public_token"]) > 20
            assert settings["widget_color"] == "#123456"

        def test_generate_conversations_public_token_requires_admin(self):
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()
            response = self.client.post(f"/api/environments/{self.team.id}/generate_conversations_public_token/")
            assert response.status_code == status.HTTP_403_FORBIDDEN

        def test_logs_settings_retention_24_hour_restriction(self):
            # Set initial retention - first update doesn't set retention_last_updated
            with freeze_time("2025-01-01T00:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 30}},
                )
                assert response.status_code == status.HTTP_200_OK
                assert not hasattr(response.json()["logs_settings"], "retention_last_updated")

            # update retention, should set retention_last_updated
            with freeze_time("2025-01-01T00:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 14}},
                )
                assert response.status_code == status.HTTP_200_OK
                assert response.json()["logs_settings"]["retention_last_updated"] is not None

            # Try to update retention within 24 hours - should fail
            with freeze_time("2025-01-01T12:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 90}},
                )
                assert response.status_code == status.HTTP_400_BAD_REQUEST
                assert "24 hours" in response.json()["detail"]

            # Try to update retention after 24 hours - should succeed
            with freeze_time("2025-01-02T00:00:01Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 90}},
                )
                assert response.status_code == status.HTTP_200_OK

        def test_logs_settings_retention_invalid_values_rejected(self):
            for invalid_days in [7, 15, 20, 45, 100]:
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": invalid_days}},
                )
                assert response.status_code == status.HTTP_400_BAD_REQUEST, (
                    f"Expected 400 for retention_days={invalid_days}"
                )
                assert "retention_days must be one of" in response.json()["detail"]

        def test_logs_settings_non_retention_changes_not_restricted(self):
            # Set initial retention
            with freeze_time("2025-01-01T00:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 30}},
                )
                assert response.status_code == status.HTTP_200_OK

            with freeze_time("2025-01-01T00:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {"logs_settings": {"retention_days": 14}},
                )
                assert response.status_code == status.HTTP_200_OK

            # Change other settings within 24 hours - should succeed
            with freeze_time("2025-01-01T12:00:00Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {
                        "logs_settings": {
                            "retention_days": 14,  # Same retention
                            "json_parse_logs": True,
                        }
                    },
                )
                assert response.status_code == status.HTTP_200_OK

            # Change retention after 24 hours - should succeed
            with freeze_time("2025-01-02T00:00:01Z"):
                response = self.client.patch(
                    "/api/environments/@current/",
                    {
                        "logs_settings": {
                            "retention_days": 30,
                        }
                    },
                )
                assert response.status_code == status.HTTP_200_OK

        def test_read_only_api_key_cannot_update_team_config_fields(self):
            """API keys with only project:read scope should not be able to modify config fields."""
            api_key = self.create_personal_api_key_with_scopes(["project:read"])

            response = self.client.patch(
                "/api/environments/@current/",
                {"timezone": "Europe/Lisbon"},
                headers={"authorization": f"Bearer {api_key}"},
            )

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
            self.assertIn("project:write", response.json().get("detail", ""))

            # Verify no changes were made
            self.team.refresh_from_db()
            self.assertEqual(self.team.timezone, "UTC")

        def test_write_api_key_can_update_team_config_fields(self):
            """API keys with project:write scope should be able to modify config fields."""
            api_key = self.create_personal_api_key_with_scopes(["project:write"])

            response = self.client.patch(
                "/api/environments/@current/",
                {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
                headers={"authorization": f"Bearer {api_key}"},
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Verify changes were made
            self.team.refresh_from_db()
            self.assertEqual(self.team.timezone, "Europe/Lisbon")
            self.assertEqual(self.team.session_recording_opt_in, True)

        def _get_model_for_name_field(self):
            """Returns the model whose 'name' field is updated by the current endpoint.

            /api/environments/ updates Team.name, /api/projects/ updates Project.name.
            This allows tests to work correctly when inherited by TestProjectAPI.
            """
            if isinstance(self.client, EnvironmentToProjectRewriteClient):
                return self.project
            return self.team

        def test_read_only_api_key_cannot_update_team_non_config_fields(self):
            """API keys with only project:read scope should not be able to modify non-config fields like name."""
            api_key = self.create_personal_api_key_with_scopes(["project:read"])
            model = self._get_model_for_name_field()
            original_name = model.name

            response = self.client.patch(
                "/api/environments/@current/",
                {"name": "New Team Name"},
                headers={"authorization": f"Bearer {api_key}"},
            )

            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

            # Verify no changes were made
            model.refresh_from_db()
            self.assertEqual(model.name, original_name)

        def test_write_api_key_can_update_team_non_config_fields(self):
            """API keys with project:write scope should be able to modify non-config fields like name."""
            api_key = self.create_personal_api_key_with_scopes(["project:write"])
            model = self._get_model_for_name_field()

            response = self.client.patch(
                "/api/environments/@current/",
                {"name": "New Team Name"},
                headers={"authorization": f"Bearer {api_key}"},
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Verify changes were made
            model.refresh_from_db()
            self.assertEqual(model.name, "New Team Name")

        def test_session_auth_member_can_still_update_member_safe_config_fields(self):
            """Session-based auth (browser users) with member role can still update member-safe
            config fields (the onboarding-style toggles the UI does not gate behind
            TeamMembershipLevel.Admin). Admin-only fields are tested separately in
            test_team_admin_authorization_vulnerability.py.
            """
            self.organization_membership.level = OrganizationMembership.Level.MEMBER
            self.organization_membership.save()

            response = self.client.patch(
                "/api/environments/@current/",
                {"session_recording_opt_in": True, "surveys_opt_in": True},
            )

            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Verify changes were made
            self.team.refresh_from_db()
            self.assertEqual(self.team.session_recording_opt_in, True)
            self.assertEqual(self.team.surveys_opt_in, True)

        @override_settings(DEBUG=True)
        def test_update_proactive_tasks_enabled_true_creates_signal_source_config(self):
            from products.signals.backend.models import SignalSourceConfig

            response = self.client.patch("/api/environments/@current/", {"proactive_tasks_enabled": True})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertTrue(
                SignalSourceConfig.objects.filter(
                    team=self.team,
                    source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                    source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                    enabled=True,
                ).exists()
            )

        @override_settings(DEBUG=True)
        def test_update_proactive_tasks_enabled_false_deletes_signal_source_config(self):
            from products.signals.backend.models import SignalSourceConfig

            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                enabled=True,
                config={},
            )

            response = self.client.patch("/api/environments/@current/", {"proactive_tasks_enabled": False})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertFalse(
                SignalSourceConfig.objects.filter(
                    team=self.team,
                    source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                    source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                ).exists()
            )

        @override_settings(DEBUG=True)
        def test_update_proactive_tasks_enabled_true_is_idempotent(self):
            from products.signals.backend.models import SignalSourceConfig

            SignalSourceConfig.objects.create(
                team=self.team,
                source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                enabled=True,
                config={},
            )

            response = self.client.patch("/api/environments/@current/", {"proactive_tasks_enabled": True})
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            self.assertEqual(
                SignalSourceConfig.objects.filter(
                    team=self.team,
                    source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
                    source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
                ).count(),
                1,
            )

        def test_can_set_session_recording_trigger_groups(self):
            """Test that we can create and update session_recording_trigger_groups field"""
            trigger_groups = {
                "version": 2,
                "groups": [
                    {
                        "id": "test-group-1",
                        "name": "Test Group",
                        "sampleRate": 0.5,
                        "minDurationMs": 5000,
                        "conditions": {
                            "matchType": "any",
                            "events": ["pageview"],
                            "flag": "test-flag-key",
                        },
                    }
                ],
            }

            # Test creating with trigger groups
            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"] == trigger_groups

            # Test that it persisted
            self.team.refresh_from_db()
            assert self.team.session_recording_trigger_groups == trigger_groups

            # Test updating
            trigger_groups["groups"][0]["sampleRate"] = 1.0  # type: ignore
            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"]["groups"][0]["sampleRate"] == 1.0

            # Test clearing (set to null)
            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": None},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"] is None

        @parameterized.expand(
            [
                (
                    "missing_version",
                    {"groups": []},
                    "version",
                ),
                (
                    "invalid_version",
                    {"version": 1, "groups": []},
                    "version",
                ),
                (
                    "missing_groups",
                    {"version": 2},
                    "groups",
                ),
                (
                    "invalid_sample_rate_above_one",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 1.5,
                                "conditions": {"matchType": "any"},
                            }
                        ],
                    },
                    "samplerate",
                ),
                (
                    "negative_sample_rate",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": -0.1,
                                "conditions": {"matchType": "any"},
                            }
                        ],
                    },
                    "samplerate",
                ),
                (
                    "invalid_match_type",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {"matchType": "invalid"},
                            }
                        ],
                    },
                    "matchtype",
                ),
                (
                    "invalid_regex",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "urls": [{"url": "[invalid(regex", "matching": "regex"}],
                                },
                            }
                        ],
                    },
                    "regex",
                ),
                (
                    "invalid_min_duration_negative",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "minDurationMs": -100,
                                "conditions": {"matchType": "any"},
                            }
                        ],
                    },
                    "mindurationms",
                ),
                (
                    "invalid_min_duration_too_large",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "minDurationMs": 40000,
                                "conditions": {"matchType": "any"},
                            }
                        ],
                    },
                    "mindurationms",
                ),
                (
                    "invalid_min_duration_boolean",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "minDurationMs": True,
                                "conditions": {"matchType": "any"},
                            }
                        ],
                    },
                    "mindurationms",
                ),
                (
                    "event_object_missing_name",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [{"properties": []}],
                                },
                            }
                        ],
                    },
                    "name",
                ),
                (
                    "event_invalid_type",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [123],
                                },
                            }
                        ],
                    },
                    "string or object",
                ),
                (
                    "event_property_missing_type",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [
                                        {
                                            "name": "purchase",
                                            "properties": [{"key": "amount", "operator": "gt", "value": 100}],
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                    "type",
                ),
                (
                    "event_property_invalid_type",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [
                                        {
                                            "name": "purchase",
                                            "properties": [
                                                {"key": "amount", "type": "hogql", "operator": "gt", "value": 100}
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                    "type",
                ),
                (
                    "event_property_missing_key",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [
                                        {
                                            "name": "purchase",
                                            "properties": [{"type": "event", "operator": "exact", "value": "foo"}],
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                    "key",
                ),
                (
                    "event_property_invalid_operator",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [
                                        {
                                            "name": "purchase",
                                            "properties": [
                                                {"key": "amount", "type": "event", "operator": "banana", "value": 100}
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                    "invalid operator",
                ),
                (
                    "group_level_property_invalid_operator",
                    {
                        "version": 2,
                        "groups": [
                            {
                                "id": "test",
                                "sampleRate": 0.5,
                                "conditions": {
                                    "matchType": "any",
                                    "events": [{"name": "error"}],
                                    "properties": [
                                        {"key": "country", "type": "person", "operator": "banana", "value": "US"}
                                    ],
                                },
                            }
                        ],
                    },
                    "invalid operator",
                ),
            ]
        )
        def test_session_recording_trigger_groups_validation_errors(
            self, name: str, trigger_groups: dict, expected_error_fragment: str
        ):
            """Test various validation failures for trigger groups"""
            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert expected_error_fragment in str(response.json()).lower()

        def test_session_recording_trigger_groups_complex_valid_config(self):
            """Test that complex valid configurations pass validation"""
            trigger_groups = {
                "version": 2,
                "groups": [
                    {
                        "id": "errors",
                        "name": "Error Tracking",
                        "sampleRate": 1.0,
                        "minDurationMs": 0,
                        "conditions": {
                            "matchType": "any",
                            "events": ["error", "crash"],
                            "urls": [{"url": "/checkout.*", "matching": "regex"}],
                        },
                    },
                    {
                        "id": "feature-flag",
                        "name": "Feature Flag Testing",
                        "sampleRate": 0.5,
                        "minDurationMs": 10000,
                        "conditions": {
                            "matchType": "all",
                            "flag": {"key": "variant-test", "variant": "control"},
                        },
                    },
                    {
                        "id": "simple-flag",
                        "name": "Simple Flag",
                        "sampleRate": 0.3,
                        "conditions": {
                            "matchType": "any",
                            "flag": "simple-feature-flag",
                        },
                    },
                ],
            }

            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"] == trigger_groups

        def test_session_recording_trigger_groups_with_event_objects_and_properties(self):
            trigger_groups = {
                "version": 2,
                "groups": [
                    {
                        "id": "rich-events",
                        "name": "Events with WHERE clauses",
                        "sampleRate": 1.0,
                        "conditions": {
                            "matchType": "all",
                            "events": [
                                "simple_event",
                                {
                                    "name": "purchase",
                                    "properties": [
                                        {"key": "amount", "type": "event", "operator": "gt", "value": 100},
                                        {"key": "currency", "type": "event", "operator": "exact", "value": "USD"},
                                    ],
                                },
                                {"name": "$exception"},
                            ],
                            "urls": [
                                {
                                    "url": "/checkout.*",
                                    "matching": "regex",
                                }
                            ],
                        },
                    },
                ],
            }

            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"] == trigger_groups

        def test_session_recording_trigger_groups_with_group_level_properties(self):
            trigger_groups = {
                "version": 2,
                "groups": [
                    {
                        "id": "us-errors",
                        "name": "US errors on checkout",
                        "sampleRate": 1.0,
                        "conditions": {
                            "matchType": "any",
                            "events": [{"name": "$exception"}, {"name": "purchase_error"}],
                            "properties": [
                                {
                                    "key": "$current_url",
                                    "type": "event",
                                    "operator": "icontains",
                                    "value": ["checkout.acme.com", "payments.acme.com"],
                                },
                                {"key": "country", "type": "person", "operator": "exact", "value": "US"},
                            ],
                        },
                    },
                ],
            }

            response = self.client.patch(
                f"/api/environments/{self.team.id}/",
                {"session_recording_trigger_groups": trigger_groups},
            )

            assert response.status_code == status.HTTP_200_OK
            assert response.json()["session_recording_trigger_groups"] == trigger_groups

    return TestTeamAPI


class EnvironmentToProjectRewriteClient(test.APIClient):
    """
    This client rewrites all requests to the /api/environments/ endpoint ("proper" environments endpoint)
    to /api/projects/ (previously known as the "team" endpoint). Allows us to test for backwards compatibility of
    the /api/projects/ endpoint - for use in `test_project.py`.
    """

    def generic(
        self,
        method,
        path,
        data="",
        content_type="application/octet-stream",
        secure=False,
        *,
        headers=None,
        **extra,
    ):
        path = path.replace("/api/projects/@current/environments/", "/api/projects/").replace(
            "/api/environments/", "/api/projects/"
        )
        return super().generic(method, path, data, content_type, secure, headers=headers, **extra)


def create_team(organization: Organization, name: str = "Test team", timezone: str = "UTC") -> Team:
    """
    This is a helper that just creates a team. It currently uses the orm, but we
    could use either the api, or django admin to create, to get better parity
    with real world scenarios.
    """
    return Team.objects.create(
        organization=organization,
        name=name,
        ingested_event=True,
        completed_snippet_onboarding=True,
        is_demo=True,
        timezone=timezone,
        base_currency="USD",
    )


class TestTeamAPI(team_api_test_factory()):  # type: ignore
    def test_teams_outside_personal_api_key_scoped_teams_not_listed(self):
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        _, team_in_other_project = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user
        )
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_teams=[other_team_in_project.id],
            scopes=["*"],
        )

        # Team-scoped keys cannot list all environments — they can only access specific teams directly
        response = self.client.get("/api/environments/", headers={"authorization": f"Bearer {personal_api_key}"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # But they can access the scoped team directly
        response = self.client.get(
            f"/api/environments/{other_team_in_project.id}/",
            headers={"authorization": f"Bearer {personal_api_key}"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], other_team_in_project.id)

    def test_teams_outside_personal_api_key_scoped_organizations_not_listed(self):
        other_org, __, team_in_other_org = Organization.objects.bootstrap(self.user)
        personal_api_key = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="X",
            user=self.user,
            last_used_at="2021-08-25T21:09:14",
            secure_value=hash_key_value(personal_api_key),
            scoped_organizations=[other_org.id],
            scopes=["*"],
        )

        response = self.client.get("/api/environments/", headers={"authorization": f"Bearer {personal_api_key}"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {team["id"] for team in response.json()["results"]},
            {team_in_other_org.id},
            "Only the team belonging to the scoped organization should be listed, the other one should be excluded",
        )

    def test_teams_outside_oauth_scoped_teams_causes_403(self):
        # TODO: This should filter out the teams to the scoped teams, but it causes a 403 due to a bug in APIScopePermission for list endpoints.
        other_team_in_project = Team.objects.create(organization=self.organization, project=self.project)
        _, team_in_other_project = Project.objects.create_with_team(
            organization=self.organization, initiating_user=self.user
        )

        oauth_app = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_id="test_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )

        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            user=self.user,
            token="pha_test_oauth_token",
            scope="*",
            expires=timezone.now() + timedelta(hours=1),
            scoped_teams=[other_team_in_project.id],
        )

        response = self.client.get("/api/environments/", headers={"authorization": f"Bearer {access_token.token}"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_teams_outside_oauth_scoped_organizations_not_listed(self):
        other_org, __, team_in_other_org = Organization.objects.bootstrap(self.user)

        oauth_app = OAuthApplication.objects.create(
            name="Test OAuth App",
            client_id="test_client_id",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            user=self.user,
        )

        access_token = OAuthAccessToken.objects.create(
            application=oauth_app,
            user=self.user,
            token="pha_test_oauth_token",
            scope="*",
            expires=timezone.now() + timedelta(hours=1),
            scoped_organizations=[str(other_org.id)],
        )

        response = self.client.get("/api/environments/", headers={"authorization": f"Bearer {access_token.token}"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            {team["id"] for team in response.json()["results"]},
            {team_in_other_org.id},
            "Only the team belonging to the scoped organization should be listed, the other one should be excluded",
        )

    @override_settings(SITE_URL="https://eu.posthog.com", CLOUD_DEPLOYMENT="EU")
    def test_new_eu_organization_defaults_to_anonymize_ips_true(self):
        """New organizations on EU cloud should default to default_anonymize_ips=True"""
        new_org = Organization.objects.create(name="EU Test Org")

        # Should automatically be True for EU cloud
        self.assertTrue(new_org.default_anonymize_ips)

    @override_settings(SITE_URL="https://us.posthog.com", CLOUD_DEPLOYMENT="US")
    def test_new_us_organization_defaults_to_anonymize_ips_false(self):
        """New organizations on US cloud should default to default_anonymize_ips=False"""
        new_org = Organization.objects.create(name="US Test Org")

        # Should be False for US cloud
        self.assertFalse(new_org.default_anonymize_ips)

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT=None)
    def test_new_selfhosted_organization_defaults_to_anonymize_ips_false(self):
        """New organizations on self-hosted should default to default_anonymize_ips=False"""
        new_org = Organization.objects.create(name="Self-Hosted Test Org")

        # Should be False for self-hosted
        self.assertFalse(new_org.default_anonymize_ips)

    def test_team_member_can_write_to_team_config_with_member_access_control(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        # Default access control to member for team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=self.team.id,
            access_level="admin",
        )

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["timezone"], "Europe/Lisbon")
        self.assertEqual(response_data["session_recording_opt_in"], True)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "Europe/Lisbon")
        self.assertEqual(self.team.session_recording_opt_in, True)

    def test_team_member_cannot_write_to_team_config_with_no_access_access_control(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        # Default access control to member for team
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=self.team.id,
            access_level="none",
        )

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "UTC")
        self.assertEqual(self.team.session_recording_opt_in, False)

    def test_team_member_can_write_to_member_safe_team_config_without_access_control(self):
        # Member-safe team config (e.g. session_recording_opt_in, which onboarding flips) must
        # remain writable by org MEMBERs even without paid access control. Admin-only fields
        # like `timezone` are exercised separately in
        # posthog/api/test/test_team_admin_authorization_vulnerability.py.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        response = self.client.patch(
            "/api/environments/@current/",
            {"session_recording_opt_in": True, "surveys_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["session_recording_opt_in"], True)
        self.assertEqual(response_data["surveys_opt_in"], True)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.session_recording_opt_in, True)
        self.assertEqual(self.team.surveys_opt_in, True)

    def test_team_member_cannot_write_to_admin_team_config_without_access_control(self):
        # Regression test for the admin-authorization bypass: members must NOT be able to
        # change admin-only settings via the API even when the org has no paid access control,
        # because the frontend gates these settings behind TeamMembershipLevel.Admin.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.team.refresh_from_db()
        self.assertNotEqual(self.team.timezone, "Europe/Lisbon")

    def test_team_admin_can_write_to_team_patch_with_access_control(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=self.team.id,
            access_level="none",
        )

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response_data = response.json()
        self.assertEqual(response_data["timezone"], "Europe/Lisbon")
        self.assertEqual(response_data["session_recording_opt_in"], True)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "Europe/Lisbon")
        self.assertEqual(self.team.session_recording_opt_in, True)

    def test_team_member_cannot_write_to_team_patch_with_access_control(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=self.team.id,
            access_level="none",
        )

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon", "session_recording_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Verify no changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.timezone, "UTC")
        self.assertEqual(self.team.session_recording_opt_in, False)

    @parameterized.expand(
        [
            ("default_admin_access", False),
            ("restricted_project_member_access", True),
        ]
    )
    def test_web_analytics_editor_can_write_app_urls_with_access_control(self, _name, restrict_project_to_member):
        # A web analytics editor (org member, not project admin) must be able to manage the toolbar /
        # web analytics authorized URLs. `app_urls` carries a web-analytics-editor field access control,
        # and web analytics defaults to editor, so an editor passes the field-level check. This must hold
        # even on a restricted project where the editor's effective project access is only `member` — the
        # request gate must not demand project admin for `app_urls`, or the field-level check never runs.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        if restrict_project_to_member:
            # Lower the project's baseline from the implicit admin default to member, so the acting
            # user is a project member but not an admin.
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=self.team.id,
                access_level="member",
            )

        response = self.client.patch(
            "/api/environments/@current/",
            {"app_urls": ["https://app.example.com"]},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.json())

        self.team.refresh_from_db()
        self.assertEqual(self.team.app_urls, ["https://app.example.com"])

    def test_web_analytics_viewer_cannot_write_app_urls_with_access_control(self):
        # Restricting web analytics below editor must block managing authorized URLs.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        # Default the whole team's web analytics access down to viewer.
        AccessControl.objects.create(
            team=self.team,
            resource="web_analytics",
            resource_id=None,
            access_level="viewer",
        )

        response = self.client.patch(
            "/api/environments/@current/",
            {"app_urls": ["https://app.example.com"]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.team.refresh_from_db()
        self.assertNotIn("https://app.example.com", self.team.app_urls)

    def test_team_member_can_write_to_member_safe_team_patch_without_access_control(self):
        # See test_team_member_can_write_to_member_safe_team_config_without_access_control above:
        # member-safe fields stay writable; admin-only fields (timezone) are covered separately.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        self.organization.available_product_features = [
            {
                "key": AvailableFeature.ACCESS_CONTROL,
                "name": AvailableFeature.ACCESS_CONTROL,
            },
        ]
        self.organization.save()

        response = self.client.patch(
            "/api/environments/@current/",
            {"session_recording_opt_in": True, "surveys_opt_in": True},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify changes were made
        self.team.refresh_from_db()
        self.assertEqual(self.team.session_recording_opt_in, True)
        self.assertEqual(self.team.surveys_opt_in, True)

    @freeze_time("2025-01-01T00:00:00Z")
    def test_settings_as_of_requires_at_param(self):
        response = self.client.get("/api/environments/@current/settings_as_of/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Response may contain either a DRF detail or field-specific error
        payload = response.json()
        assert (payload.get("detail")) or (payload.get("at"))

    def test_settings_as_of_returns_snapshot_with_scope(self):
        # Initial state at T0 is UTC (default)
        with freeze_time("2025-01-01T00:00:00Z"):
            # no change, timezone remains "UTC"
            pass

        # Change timezone at T1
        with freeze_time("2025-01-02T00:00:00Z"):
            patch_response = self.client.patch("/api/environments/@current/", {"timezone": "Europe/Lisbon"})
            assert patch_response.status_code == status.HTTP_200_OK, patch_response.json()

        # Query snapshot as of T0 + 12h - expect UTC
        response = self.client.get(
            "/api/environments/@current/settings_as_of/?at=2025-01-01T12:00:00Z"
            "&scope=timezone&scope=session_recording_sample_rate"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        assert set(data.keys()) == {"timezone", "session_recording_sample_rate"}
        assert data["timezone"] == "UTC"
        # May be null if not set at that time
        assert "session_recording_sample_rate" in data

    def test_settings_as_of_full_snapshot_and_filtering(self):
        # Set some configs over time to create activity
        with freeze_time("2025-02-01T00:00:00Z"):
            # Set opt_in true
            r1 = self.client.patch("/api/environments/@current/", {"session_recording_opt_in": True})
            assert r1.status_code == status.HTTP_200_OK

        with freeze_time("2025-02-02T00:00:00Z"):
            # Set sample rate and masking config
            r2 = self.client.patch(
                "/api/environments/@current/",
                {
                    "session_recording_sample_rate": 0.5,
                    "session_recording_masking_config": {"maskAllInputs": True},
                },
            )
            assert r2.status_code == status.HTTP_200_OK

        # Snapshot as of between the two changes - should include first change, not the second
        response = self.client.get(
            "/api/environments/@current/settings_as_of/?at=2025-02-01T12:00:00Z"
            "&scope=session_recording_opt_in&scope=session_recording_sample_rate&scope=session_recording_masking_config"
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        data = response.json()
        # opt_in should be True (set on 2025-02-01)
        assert data["session_recording_opt_in"] is True
        # sample_rate and masking_config should reflect pre-change values at that time
        assert "session_recording_sample_rate" in data
        assert data["session_recording_masking_config"] is None

    def test_settings_as_of_scope_only_includes_requested_keys(self):
        with freeze_time("2025-03-01T00:00:00Z"):
            r = self.client.patch(
                "/api/environments/@current/",
                {"timezone": "Europe/London", "session_recording_opt_in": False},
            )
            assert r.status_code == status.HTTP_200_OK

        # Ask only for timezone key
        response = self.client.get("/api/environments/@current/settings_as_of/?at=2025-03-01T00:00:01Z&scope=timezone")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert sorted(data.keys()) == ["timezone"]
        assert data["timezone"] in ("UTC", "Europe/London")

    @parameterized.expand(
        [
            (
                "missing_key",
                [{"type": "person", "operator": "exact", "value": "posthog.com"}],
            ),
            (
                "invalid_type",
                [{"key": "email", "type": "not_a_type", "operator": "exact", "value": "posthog.com"}],
            ),
            (
                "invalid_operator",
                [{"key": "email", "type": "person", "operator": "not_an_operator", "value": "posthog.com"}],
            ),
            (
                "invalid_cohort_value",
                [{"key": "id", "type": "cohort", "operator": "in", "value": "not-a-cohort-id"}],
            ),
        ]
    )
    def test_validate_test_account_filters_rejects_invalid_filters(
        self, _name: str, test_account_filters: list[dict[str, Any]]
    ):
        original_test_account_filters = self.team.test_account_filters

        response = self.client.patch(
            f"/api/environments/{self.team.id}/",
            {"test_account_filters": test_account_filters},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "test_account_filters")
        self.assertIn("Must provide an array of valid property filters.", response.json()["detail"])

        self.team.refresh_from_db()
        self.assertEqual(self.team.test_account_filters, original_test_account_filters)

    def test_validate_test_account_filters_allows_is_set_filters_without_value(self):
        response = self.client.patch(
            f"/api/environments/{self.team.id}/",
            {"test_account_filters": [{"key": "email", "type": "person", "operator": "is_set"}]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["test_account_filters"],
            [{"key": "email", "type": "person", "operator": "is_set"}],
        )


class TestTeamSerializerHomeViewWins(APIBaseTest):
    def setUp(self):
        super().setUp()
        _reset_default_data_color_theme_id_cache()
        self.addCleanup(_reset_default_data_color_theme_id_cache)

    def test_cached_group_types_for_team_memoises_per_instance(self):
        # has_group_types and group_types are sibling SerializerMethodFields; previously
        # each hit Redis. They now share a request-scoped memo on the team instance,
        # via the helper in posthog/models/group_type_mapping.py.
        with patch("posthog.models.group_type_mapping.get_group_types_for_project", return_value=[]) as mock_fetch:
            cached_group_types_for_team(self.team)
            cached_group_types_for_team(self.team)
            cached_group_types_for_team(self.team)
        assert mock_fetch.call_count == 1

        # Different team instance bypasses the memo: a single mock spanning both
        # instances must see exactly one fetch (the fresh one), not zero.
        fresh_team = Team.objects.get(pk=self.team.pk)
        with patch("posthog.models.group_type_mapping.get_group_types_for_project", return_value=[]) as mock_fetch:
            cached_group_types_for_team(self.team)  # cached on self.team
            cached_group_types_for_team(fresh_team)  # uncached on fresh
        assert mock_fetch.call_count == 1
        assert mock_fetch.call_args.args == (fresh_team.project_id,)

    def test_default_data_color_theme_id_is_cached_for_process_lifetime(self):
        # System-wide default DataColorTheme is a deploy-time fixture; cache for
        # process lifetime to skip a per-render PG round-trip on the home view.
        with patch("posthog.api.team.DataColorTheme.objects") as mock_objects:
            chained = mock_objects.filter.return_value.order_by.return_value.values_list.return_value
            chained.first.return_value = 42

            assert _default_data_color_theme_id() == 42
            assert _default_data_color_theme_id() == 42
            assert _default_data_color_theme_id() == 42

        assert mock_objects.filter.call_count == 1

    def test_default_data_color_theme_id_does_not_cache_none(self):
        # If the very first call lands before the data migration is applied, a
        # None must NOT be cached - subsequent calls should retry so we recover
        # automatically once the row appears.
        with patch("posthog.api.team.DataColorTheme.objects") as mock_objects:
            chained = mock_objects.filter.return_value.order_by.return_value.values_list.return_value
            chained.first.return_value = None

            assert _default_data_color_theme_id() is None
            assert _default_data_color_theme_id() is None

        assert mock_objects.filter.call_count == 2

        with patch("posthog.api.team.DataColorTheme.objects") as mock_objects:
            chained = mock_objects.filter.return_value.order_by.return_value.values_list.return_value
            chained.first.return_value = 7

            assert _default_data_color_theme_id() == 7
            assert _default_data_color_theme_id() == 7

        assert mock_objects.filter.call_count == 1


class TestGetOrMintLiveEventsToken(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    @parameterized.expand(
        [
            ("authenticated_user", False),
            ("anonymous_user", True),
        ]
    )
    def test_returns_a_signed_jwt_with_expected_claims(self, _name: str, anonymous: bool) -> None:
        from posthog.api.team import get_or_mint_live_events_token
        from posthog.jwt import PosthogJwtAudience, decode_jwt

        user_id = None if anonymous else self.user.id
        token = get_or_mint_live_events_token(self.team, user_id)
        claims = decode_jwt(token, PosthogJwtAudience.LIVESTREAM)
        assert claims["team_id"] == self.team.id
        assert claims["api_token"] == self.team.api_token
        assert claims["user_id"] == user_id
        assert claims["organization_id"] == str(self.team.organization_id)

    @parameterized.expand(
        [
            ("authenticated_user", False),
            ("anonymous_user", True),
        ]
    )
    def test_second_call_returns_cached_token_without_re_signing(self, _name: str, anonymous: bool) -> None:
        from posthog.api.team import get_or_mint_live_events_token

        user_id = None if anonymous else self.user.id
        first = get_or_mint_live_events_token(self.team, user_id)
        with patch("posthog.api.team.encode_jwt") as mock_encode:
            second = get_or_mint_live_events_token(self.team, user_id)
        mock_encode.assert_not_called()
        assert first == second

    @parameterized.expand(
        [
            # name, mutation_callback (called with self) describing the cache-key
            # component that should diverge between two calls
            ("user_id changes", lambda self: {"first_user_id": self.user.id, "second_user_id": self.user.id + 9999}),
            (
                "anonymous vs authenticated diverge",
                lambda self: {"first_user_id": None, "second_user_id": self.user.id},
            ),
            ("api_token rotates", lambda self: {"rotate_api_token": True}),
        ]
    )
    def test_cache_key_component_changes_force_a_fresh_mint(self, _name: str, mutation_factory) -> None:
        from posthog.api.team import get_or_mint_live_events_token

        mutation = mutation_factory(self)
        first_user_id = mutation.get("first_user_id", self.user.id)
        second_user_id = mutation.get("second_user_id", self.user.id)
        rotate_api_token = mutation.get("rotate_api_token", False)

        token_before = get_or_mint_live_events_token(self.team, first_user_id)
        if rotate_api_token:
            self.team.api_token = "rotated_token_value"
        token_after = get_or_mint_live_events_token(self.team, second_user_id)
        assert token_before != token_after

    def test_signing_key_rotation_partitions_the_cache_namespace(self) -> None:
        # JWT signing-key rotation must invalidate cached tokens automatically — otherwise
        # the livestream service would reject the cached old-key signatures for up
        # to the cache TTL. We embed a fingerprint of JWT_SIGNING_KEY in the cache key so
        # the namespace partitions cleanly on rotation.
        from posthog.api.team import get_or_mint_live_events_token

        token_old_key = get_or_mint_live_events_token(self.team, self.user.id)
        with override_settings(JWT_SIGNING_KEY="completely-different-rotated-secret"):
            token_new_key = get_or_mint_live_events_token(self.team, self.user.id)
        assert token_old_key != token_new_key


# Sensitive Team/Project settings the frontend gates behind
# `TeamMembershipLevel.Admin` AND that ordinary members are not expected to flip
# from any onboarding/dashboard surface. Each tuple is
# (field, value_to_patch, attr_on_team_to_assert).
# Values are chosen to differ from the Team-model default so a successful PATCH would
# observably change the persisted state.
_ADMIN_GATED_TEAM_CONFIG_FIELDS: list[tuple[str, Any, str]] = [
    ("timezone", "Europe/Lisbon", "timezone"),
    ("anonymize_ips", True, "anonymize_ips"),
    ("autocapture_opt_out", True, "autocapture_opt_out"),
    ("data_attributes", ["data-cy"], "data_attributes"),
    ("week_start_day", 1, "week_start_day"),
    ("path_cleaning_filters", [{"alias": "x", "regex": "/x/.*"}], "path_cleaning_filters"),
    # capture_console_log_opt_in defaults to True, so patch with False to observe change.
    ("capture_console_log_opt_in", False, "capture_console_log_opt_in"),
    ("heatmaps_opt_in", True, "heatmaps_opt_in"),
    ("recording_domains", ["https://evil.example.com"], "recording_domains"),
    ("session_recording_sample_rate", "0.5", "session_recording_sample_rate"),
    # capture_dead_clicks defaults to False so True is observable. Exposed by
    # TeamSerializer but NOT by ProjectBackwardCompatSerializer — env-only.
    ("capture_dead_clicks", True, "capture_dead_clicks"),
]

# Subset of _ADMIN_GATED_TEAM_CONFIG_FIELDS that are also patchable via /api/projects/
# (i.e. listed in ProjectBackwardCompatSerializer.Meta.fields). Fields like
# `capture_dead_clicks` and `onboarding_tasks` exist on Team but are not exposed by the
# project serializer, so they're not part of the projects-side attack surface and don't
# belong in the projects-side regression set.
_ADMIN_GATED_TEAM_CONFIG_FIELDS_FOR_PROJECTS: list[tuple[str, Any, str]] = [
    f for f in _ADMIN_GATED_TEAM_CONFIG_FIELDS if f[0] != "capture_dead_clicks"
]

# Settings ordinary members are EXPECTED to flip from the UI today (onboarding flow,
# dashboards, primary-dashboard pinning, etc.). These should keep working for MEMBER
# after the fix — captured as positive regression tests so the security fix doesn't
# silently break onboarding for invitees.
_MEMBER_SAFE_TEAM_CONFIG_FIELDS: list[tuple[str, Any, str]] = [
    ("session_recording_opt_in", True, "session_recording_opt_in"),
    ("autocapture_exceptions_opt_in", True, "autocapture_exceptions_opt_in"),
    ("autocapture_web_vitals_opt_in", True, "autocapture_web_vitals_opt_in"),
    ("surveys_opt_in", True, "surveys_opt_in"),
    ("has_completed_onboarding_for", {"product_analytics": True}, "has_completed_onboarding_for"),
    ("completed_snippet_onboarding", True, "completed_snippet_onboarding"),
]

# Subset of _MEMBER_SAFE_TEAM_CONFIG_FIELDS that are also exposed by the project serializer.
# `onboarding_tasks` isn't in ProjectBackwardCompatSerializer.Meta.fields, so it can't be
# patched through /api/projects/ regardless of permissions.
_MEMBER_SAFE_TEAM_CONFIG_FIELDS_FOR_PROJECTS: list[tuple[str, Any, str]] = [
    f for f in _MEMBER_SAFE_TEAM_CONFIG_FIELDS if f[0] != "onboarding_tasks"
]

# Sensitive fields the frontend treats as admin-only that aren't part of the regular
# TEAM_CONFIG flow. Captured as a regression so a MEMBER stays blocked from them when the
# org has no paid access control. `app_urls` additionally carries a web-analytics-editor
# `@field_access_control`; with access controls enabled that governs it instead (see
# test_web_analytics_editor_can_write_app_urls_with_access_control), but without it the
# blanket project-admin gate still applies here.
_UNANNOTATED_SENSITIVE_FIELDS: list[tuple[str, Any, str]] = [
    ("is_demo", True, "is_demo"),
    ("app_urls", ["https://evil.example.com"], "app_urls"),
]


class TestTeamAdminFieldAuthorization(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Demote the auto-logged-in user to a plain MEMBER. The frontend would hide
        # every setting below behind useRestrictedArea(Admin), so the API must reject too.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

    @parameterized.expand([(f[0], f[1], f[2]) for f in _ADMIN_GATED_TEAM_CONFIG_FIELDS])
    def test_member_cannot_patch_admin_gated_field_via_environments(
        self, field: str, value: Any, team_attr: str
    ) -> None:
        # Every field in this list is a TEAM_CONFIG_FIELD that is NOT a member-safe field.
        assert field in TEAM_CONFIG_FIELDS_SET, f"{field} not in TEAM_CONFIG_FIELDS_SET"
        assert field not in TEAM_CONFIG_MEMBER_FIELDS_SET, (
            f"{field} is in TEAM_CONFIG_MEMBER_FIELDS_SET — if intentionally member-safe, move"
            " it to _MEMBER_SAFE_TEAM_CONFIG_FIELDS instead."
        )

        response = self.client.patch("/api/environments/@current/", {field: value}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"Expected 403 Forbidden for MEMBER patching admin-gated field {field!r}, "
            f"got {response.status_code}: {response.json()}"
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) != value, (
            f"Field {field!r} was persisted by a MEMBER (value={value!r}) — admin-only setting was modified."
        )

    @parameterized.expand([(f[0], f[1], f[2]) for f in _ADMIN_GATED_TEAM_CONFIG_FIELDS_FOR_PROJECTS])
    def test_member_cannot_patch_admin_gated_field_via_projects(self, field: str, value: Any, team_attr: str) -> None:
        response = self.client.patch(f"/api/projects/{self.project.id}/", {field: value}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"Expected 403 Forbidden for MEMBER patching admin-gated field {field!r} via /api/projects/, "
            f"got {response.status_code}: {response.json()}"
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) != value, (
            f"Field {field!r} was persisted via /api/projects/ by a MEMBER (value={value!r}) — "
            "ProjectBackwardCompatSerializer is bypassing field-level access control."
        )

    @parameterized.expand(_UNANNOTATED_SENSITIVE_FIELDS)
    def test_member_cannot_patch_unannotated_sensitive_field_via_environments(
        self, field: str, value: Any, team_attr: str
    ) -> None:
        response = self.client.patch("/api/environments/@current/", {field: value}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"Expected 403 Forbidden for MEMBER patching unannotated sensitive field {field!r}, "
            f"got {response.status_code}: {response.json()}"
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) != value, (
            f"Unannotated field {field!r} was persisted by a MEMBER (value={value!r}). "
            "Add @field_access_control on the Team model."
        )

    @parameterized.expand(_UNANNOTATED_SENSITIVE_FIELDS)
    def test_member_cannot_patch_unannotated_sensitive_field_via_projects(
        self, field: str, value: Any, team_attr: str
    ) -> None:
        response = self.client.patch(f"/api/projects/{self.project.id}/", {field: value}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"Expected 403 Forbidden for MEMBER patching unannotated sensitive field {field!r} via /api/projects/, "
            f"got {response.status_code}: {response.json()}"
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) != value

    @parameterized.expand(_MEMBER_SAFE_TEAM_CONFIG_FIELDS)
    def test_member_can_still_patch_member_safe_field_via_environments(
        self, field: str, value: Any, team_attr: str
    ) -> None:
        assert field in TEAM_CONFIG_MEMBER_FIELDS_SET, (
            f"{field} is not declared member-safe in TEAM_CONFIG_MEMBER_FIELDS_SET. "
            "If onboarding / dashboards rely on it, add it there; otherwise remove from this test list."
        )
        response = self.client.patch("/api/environments/@current/", {field: value}, format="json")
        assert response.status_code == status.HTTP_200_OK, (
            f"MEMBER unexpectedly blocked from patching member-safe field {field!r}: "
            f"status={response.status_code}, body={response.json()}. "
            "This would break onboarding / dashboard flows for invitee users."
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) == value

    @parameterized.expand(_MEMBER_SAFE_TEAM_CONFIG_FIELDS_FOR_PROJECTS)
    def test_member_can_still_patch_member_safe_field_via_projects(
        self, field: str, value: Any, team_attr: str
    ) -> None:
        response = self.client.patch(f"/api/projects/{self.project.id}/", {field: value}, format="json")
        assert response.status_code == status.HTTP_200_OK, (
            f"MEMBER unexpectedly blocked from patching member-safe field {field!r} via /api/projects/: "
            f"status={response.status_code}, body={response.json()}."
        )
        self.team.refresh_from_db()
        assert getattr(self.team, team_attr) == value

    def test_mixed_member_and_admin_fields_is_rejected_for_member(self) -> None:
        # A member request that bundles a member-safe field with an admin-only field must
        # be rejected as a whole — otherwise an attacker could hide admin writes behind a
        # legitimate-looking onboarding patch.
        response = self.client.patch(
            "/api/environments/@current/",
            {"surveys_opt_in": True, "timezone": "Europe/Lisbon"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"Mixed member-safe + admin-only patch should be rejected: "
            f"status={response.status_code}, body={response.json()}"
        )
        self.team.refresh_from_db()
        assert self.team.timezone != "Europe/Lisbon"
        # Even the safe field must not be applied when the request is rejected.
        assert self.team.surveys_opt_in is not True

    def _enable_access_control_with_member_level(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        # Default project access for the org is "member" (not "admin"). The user is a MEMBER.
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="member",
        )

    def test_member_with_member_access_control_is_blocked_on_environments_for_admin_field(self) -> None:
        # Baseline: the existing field_access_control mixin enforces on /api/environments/
        # when access_control is on. timezone is field_access_control(..., "project", "admin").
        self._enable_access_control_with_member_level()

        response = self.client.patch("/api/environments/@current/", {"timezone": "Europe/Lisbon"}, format="json")

        assert response.status_code != status.HTTP_200_OK, (
            "Regression: /api/environments/ should reject MEMBER-level project access for "
            "field_access_control('project','admin') fields like timezone."
        )
        self.team.refresh_from_db()
        assert self.team.timezone != "Europe/Lisbon"

    def test_member_with_member_access_control_is_blocked_on_projects_for_admin_field(self) -> None:
        # /api/projects/ must also enforce: ProjectBackwardCompatSerializer now mixes in
        # UserAccessControlSerializerMixin (with a Team-aware validate override).
        self._enable_access_control_with_member_level()

        response = self.client.patch(f"/api/projects/{self.project.id}/", {"timezone": "Europe/Lisbon"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, (
            f"/api/projects/ failed to enforce field_access_control on 'timezone' for a MEMBER "
            f"(status={response.status_code}, body={response.json()}). "
            "ProjectBackwardCompatSerializer needs UserAccessControlSerializerMixin."
        )
        self.team.refresh_from_db()
        assert self.team.timezone != "Europe/Lisbon"

    def _personal_api_key(self, scopes: list[str]) -> str:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="ro",
            user=self.user,
            secure_value=hash_key_value(token),
            scopes=scopes,
        )
        return token

    def test_read_only_personal_api_key_cannot_patch_team_config(self) -> None:
        token = self._personal_api_key(["project:read"])

        response = self.client.patch(
            "/api/environments/@current/",
            {"timezone": "Europe/Lisbon"},
            format="json",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN), (
            f"Read-only personal API key was allowed to patch team config: status={response.status_code}, "
            f"body={response.json()}. The session-auth scope downgrade must remain session-only."
        )

    def test_member_cannot_delete_team(self) -> None:
        # Create a second team in the same project so the org isn't left team-less.
        other = Team.objects.create(organization=self.organization, project=self.project, name="other")
        response = self.client.delete(f"/api/environments/{other.id}/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestTeamSerializerValidationNoDB(SimpleTestCase):
    # Field-level input validation runs inside `is_valid()` (in `to_internal_value`),
    # before the object-level `validate()` that needs request context — so these never
    # touch the DB. `.errors` carries DRF's raw code (`invalid`); the HTTP envelope's
    # `invalid_input` rename and `{attr, code, detail, type}` shape are rendered by
    # exceptions-hog and covered by one endpoint smoke test in TestTeamAPI.
    def _assert_field_error(self, field: str, value: Any, expected_code: str, expected_detail: str) -> None:
        serializer = TeamSerializer(data={field: value}, partial=True)
        assert not serializer.is_valid()
        error = serializer.errors[field][0]
        assert error.code == expected_code, f"expected code {expected_code!r}, got {error.code!r}"
        assert str(error) == expected_detail, f"expected {expected_detail!r}, got {str(error)!r}"

    @parameterized.expand(
        [
            ["non numeric string", "Welwyn Garden City", "invalid", "A valid number is required."],
            ["negative number", "-1", "min_value", "Ensure this value is greater than or equal to 0."],
            ["greater than one", "1.5", "max_value", "Ensure this value is less than or equal to 1."],
            ["too many digits", "0.534", "max_decimal_places", "Ensure that there are no more than 2 decimal places."],
        ]
    )
    def test_invalid_session_recording_sample_rate(
        self, _name: str, value: Any, expected_code: str, expected_detail: str
    ) -> None:
        self._assert_field_error("session_recording_sample_rate", value, expected_code, expected_detail)

    @parameterized.expand(
        [
            ["non numeric string", "Trentham monkey forest", "invalid", "A valid integer is required."],
            ["negative number", "-1", "min_value", "Ensure this value is greater than or equal to 0."],
            ["greater than 30000", "30001", "max_value", "Ensure this value is less than or equal to 30000."],
            ["too many digits", "0.5", "invalid", "A valid integer is required."],
        ]
    )
    def test_invalid_session_recording_minimum_duration(
        self, _name: str, value: Any, expected_code: str, expected_detail: str
    ) -> None:
        self._assert_field_error(
            "session_recording_minimum_duration_milliseconds", value, expected_code, expected_detail
        )

    @parameterized.expand(
        [
            ["string", "Marple bridge", "Must provide a dictionary or None."],
            ["numeric string", "-1", "Must provide a dictionary or None."],
            ["numeric", 1, "Must provide a dictionary or None."],
            ["numeric positive string", "1", "Must provide a dictionary or None."],
            [
                "unexpected json - no id",
                {"key": "something"},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - no key",
                {"id": 1},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - only variant",
                {"variant": "1"},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - variant must be string",
                {"variant": 1},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - missing id",
                {"key": "one", "variant": "1"},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - missing key",
                {"id": "one", "variant": "1"},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
            [
                "unexpected json - neither",
                {"wat": "wat"},
                "Must provide a dictionary with only 'id' and 'key' keys. _or_ only 'id', 'key', and 'variant' keys.",
            ],
        ]
    )
    def test_invalid_session_recording_linked_flag(self, _name: str, value: Any, expected_detail: str) -> None:
        self._assert_field_error("session_recording_linked_flag", value, "invalid", expected_detail)

    @parameterized.expand(
        [
            ["string", "Marple bridge", "Must provide a dictionary or None."],
            ["numeric", "-1", "Must provide a dictionary or None."],
            [
                "unexpected json - no recordX",
                {"key": "something"},
                "Must provide a dictionary with only 'recordHeaders' and/or 'recordBody' keys.",
            ],
        ]
    )
    def test_invalid_session_recording_network_payload_capture_config(
        self, _name: str, value: Any, expected_detail: str
    ) -> None:
        self._assert_field_error("session_recording_network_payload_capture_config", value, "invalid", expected_detail)

    @parameterized.expand(
        [
            ["string", "Marple bridge", "Must provide a dictionary or None."],
            ["numeric", "-1", "Must provide a dictionary or None."],
            [
                "unexpected json - no record",
                {"key": "something"},
                "Must provide a dictionary with only allowed keys: included_event_properties, opt_in, preferred_events, excluded_events, important_user_properties.",
            ],
        ]
    )
    def test_invalid_session_replay_config_ai_config(self, _name: str, value: Any, expected_detail: str) -> None:
        self._assert_field_error("session_replay_config", {"ai_config": value}, "invalid", expected_detail)

    def test_invalid_autocapture_exceptions_opt_in_not_a_boolean(self) -> None:
        # `autocapture_exceptions_errors_to_ignore` is deliberately not here: its validation
        # lives in the object-level `validate()` (via `validate_team_attrs`), which needs
        # request context, so it stays an endpoint test in TestTeamAPI.
        self._assert_field_error(
            "autocapture_exceptions_opt_in", "Welwyn Garden City", "invalid", "Must be a valid boolean."
        )
