from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import FeatureFlag, Organization, Team


class TestFlagValueViewSet(APIBaseTest):
    def test_flag_values_boolean_flag(self):
        """Test that boolean flags return true/false values."""
        flag = FeatureFlag.objects.create(
            name="Boolean Flag",
            key="boolean-flag",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [{"name": True}, {"name": False}]
        self.assertEqual(data, expected_values)

    def test_flag_values_multivariate_flag(self):
        """Test that multivariate flags return true/false plus variant keys."""
        flag = FeatureFlag.objects.create(
            name="Multivariate Flag",
            key="multivariate-flag",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "variant1", "rollout_percentage": 50},
                        {"key": "variant2", "rollout_percentage": 50},
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [
            {"name": True},
            {"name": False},
            {"name": "variant1"},
            {"name": "variant2"},
        ]
        self.assertEqual(data, expected_values)

    def test_flag_values_missing_key_parameter(self):
        """Test that missing key parameter returns 400."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()
        self.assertEqual(data["error"], "Missing flag ID parameter")

    def test_flag_values_invalid_key_parameter(self):
        """Test that invalid key parameter returns 400."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key=invalid")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        data = response.json()
        self.assertEqual(data["error"], "Invalid flag ID - must be a valid integer")

    def test_flag_values_nonexistent_flag(self):
        """Test that nonexistent flag returns 404."""
        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key=99999")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_flag_from_different_team(self):
        """Test that flag from different team returns 404."""
        # Create a different team and flag

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")

        other_flag = FeatureFlag.objects.create(
            name="Other Flag",
            key="other-flag",
            team=other_team,
            filters={"groups": [{"rollout_percentage": 100}]},
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={other_flag.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_deleted_flag(self):
        """Test that deleted flag returns 404."""
        flag = FeatureFlag.objects.create(
            name="Deleted Flag",
            key="deleted-flag",
            team=self.team,
            filters={"groups": [{"rollout_percentage": 100}]},
            deleted=True,
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        data = response.json()
        self.assertEqual(data["error"], "Feature flag not found")

    def test_flag_values_multivariate_no_variants(self):
        """Test multivariate flag with no variants returns only true/false."""
        flag = FeatureFlag.objects.create(
            name="Multivariate No Variants",
            key="multivariate-no-variants",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {},
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [{"name": True}, {"name": False}]
        self.assertEqual(data, expected_values)

    def test_flag_values_multivariate_with_empty_variant_key(self):
        """Test multivariate flag with empty variant key ignores that variant."""
        flag = FeatureFlag.objects.create(
            name="Multivariate Empty Key",
            key="multivariate-empty-key",
            team=self.team,
            filters={
                "groups": [{"rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "valid_variant", "rollout_percentage": 50},
                        {"key": "", "rollout_percentage": 25},  # Empty key should be ignored
                        {"rollout_percentage": 25},  # No key should be ignored
                    ]
                },
            },
        )

        response = self.client.get(f"/api/projects/{self.team.project_id}/flag_value/values?key={flag.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        expected_values = [
            {"name": True},
            {"name": False},
            {"name": "valid_variant"},
        ]
        self.assertEqual(data, expected_values)
