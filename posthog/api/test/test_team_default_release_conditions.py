from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import OrganizationMembership
from posthog.models.team.extensions import get_or_create_team_extension

from products.feature_flags.backend.models import TeamFeatureFlagDefaultsConfig


class TestTeamDefaultReleaseConditions(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.url = f"/api/environments/{self.team.id}/default_release_conditions/"

    def test_get_returns_empty_defaults_for_fresh_team(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"enabled": False, "default_groups": []})

    def test_put_stores_valid_groups(self):
        groups = [
            {
                "properties": [{"key": "user_plan", "type": "person", "value": "free", "operator": "exact"}],
                "rollout_percentage": 100,
                "variant": None,
            },
            {
                "properties": [{"key": "is_managed", "type": "person", "value": "false", "operator": "exact"}],
                "rollout_percentage": 50,
                "variant": None,
            },
        ]

        response = self.client.put(
            self.url,
            {"enabled": True, "default_groups": groups},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(len(data["default_groups"]), 2)
        self.assertEqual(data["default_groups"][0]["rollout_percentage"], 100)
        self.assertEqual(data["default_groups"][1]["rollout_percentage"], 50)

    def test_put_toggles_enabled(self):
        # Enable
        response = self.client.put(
            self.url,
            {"enabled": True, "default_groups": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["enabled"])

        # Disable
        response = self.client.put(
            self.url,
            {"enabled": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["enabled"])

    def test_put_with_empty_array_clears_defaults(self):
        config = get_or_create_team_extension(self.team, TeamFeatureFlagDefaultsConfig)
        config.default_groups = [{"properties": [], "rollout_percentage": 100}]
        config.save()

        response = self.client.put(
            self.url,
            {"default_groups": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["default_groups"], [])

    @parameterized.expand(
        [
            ("non_list_groups", {"default_groups": "not a list"}, "must be a list"),
            ("missing_properties", {"default_groups": [{"rollout_percentage": 100}]}, "properties"),
            (
                "rollout_too_high",
                {"default_groups": [{"properties": [], "rollout_percentage": 150}]},
                "rollout_percentage",
            ),
            (
                "rollout_nan",
                {"default_groups": [{"properties": [], "rollout_percentage": float("nan")}]},
                "rollout_percentage",
            ),
        ]
    )
    def test_put_rejects_invalid_input(self, _name, payload, expected_error_substring):
        response = self.client.put(self.url, payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(expected_error_substring, response.json()["error"])

    def test_put_accepts_null_rollout_percentage(self):
        response = self.client.put(
            self.url,
            {"default_groups": [{"properties": [], "rollout_percentage": None}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["default_groups"][0]["rollout_percentage"])

    def test_non_admin_can_read_and_write(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.put(self.url, {"enabled": True, "default_groups": []}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_get_returns_previously_saved_config(self):
        config = get_or_create_team_extension(self.team, TeamFeatureFlagDefaultsConfig)
        config.enabled = True
        config.default_groups = [
            {
                "properties": [{"key": "plan", "type": "person", "value": "enterprise", "operator": "exact"}],
                "rollout_percentage": 100,
            }
        ]
        config.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["enabled"])
        self.assertEqual(len(data["default_groups"]), 1)
        self.assertEqual(data["default_groups"][0]["properties"][0]["key"], "plan")
