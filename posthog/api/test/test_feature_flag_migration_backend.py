from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized
from rest_framework import status

from posthog.api.feature_flag_migration import FeatureFlagMigrationViewSet


class TestFeatureFlagMigrationViewSet(APIBaseTest):
    """Test the FeatureFlagMigrationViewSet API endpoints"""

    def setUp(self):
        super().setUp()
        self.viewset = FeatureFlagMigrationViewSet()
        self.viewset.team = self.team

    def test_fetch_external_flags_missing_provider(self):
        """Test fetch external flags with missing provider"""
        request_data = {"api_key": "test-key"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/", data=request_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and API key are required", response.json()["error"])

    def test_fetch_external_flags_missing_api_key(self):
        """Test fetch external flags with missing API key"""
        request_data = {"provider": "amplitude"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/", data=request_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and API key are required", response.json()["error"])

    def test_fetch_external_flags_unsupported_provider(self):
        """Test fetch external flags with unsupported provider"""
        request_data = {"provider": "unsupported_provider", "api_key": "test-key"}

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/", data=request_data
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider 'unsupported_provider' is not supported", response.json()["error"])

    @patch("requests.get")
    def test_fetch_amplitude_flags_success(self, mock_get):
        """Test successful fetch from Amplitude API"""
        # Mock Amplitude API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "feature_flags": [
                {
                    "key": "test-flag",
                    "name": "Test Flag",
                    "description": "A test flag",
                    "enabled": True,
                    "targeting": {"rules": []},
                    "variants": [],
                }
            ]
        }
        mock_get.return_value = mock_response

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/",
            data={"provider": "amplitude", "api_key": "test-amplitude-key"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["total_flags"], 1)
        self.assertEqual(data["importable_count"], 1)
        self.assertEqual(data["non_importable_count"], 0)

        # Verify flag structure
        flag = data["importable_flags"][0]
        self.assertEqual(flag["key"], "test-flag")
        self.assertEqual(flag["name"], "Test Flag")
        self.assertTrue(flag["importable"])
        self.assertEqual(flag["metadata"]["provider"], "amplitude")

    @patch("requests.get")
    def test_fetch_amplitude_flags_api_error(self, mock_get):
        """Test handling of Amplitude API errors"""
        # Mock API error response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_get.return_value = mock_response

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/fetch_external_flags/",
            data={"provider": "amplitude", "api_key": "invalid-key"},
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to fetch flags", response.json()["error"])

    def test_single_condition_flag_detection(self):
        """Test _is_single_condition_flag method"""
        # Single condition flag (importable)
        single_condition_flag = {
            "conditions": [
                {"properties": [{"key": "country", "operator": "exact", "value": "US"}], "rollout_percentage": 100}
            ]
        }

        result = self.viewset._is_single_condition_flag(single_condition_flag)
        self.assertTrue(result)

        # Multiple condition flag (not importable)
        multiple_condition_flag = {
            "conditions": [
                {"properties": [{"key": "country", "operator": "exact", "value": "US"}], "rollout_percentage": 50},
                {"properties": [{"key": "plan", "operator": "exact", "value": "premium"}], "rollout_percentage": 30},
            ]
        }

        result = self.viewset._is_single_condition_flag(multiple_condition_flag)
        self.assertFalse(result)

        # No conditions (importable)
        no_condition_flag = {"conditions": []}

        result = self.viewset._is_single_condition_flag(no_condition_flag)
        self.assertTrue(result)

    def test_normalize_amplitude_flags(self):
        """Test _normalize_amplitude_flags method"""
        amplitude_data = {
            "feature_flags": [
                {
                    "id": "amplitude-123",
                    "key": "test-flag",
                    "name": "Test Flag",
                    "description": "Test description",
                    "enabled": True,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-02T00:00:00Z",
                    "targeting": {
                        "rules": [
                            {
                                "conditions": [{"property": "country", "operator": "equals", "value": "US"}],
                                "rollout_percentage": 100,
                                "variant": "variant_a",
                            }
                        ]
                    },
                    "variants": [
                        {"key": "variant_a", "name": "Variant A", "value": {"color": "blue"}, "rollout_percentage": 50}
                    ],
                }
            ]
        }

        result = self.viewset._normalize_amplitude_flags(amplitude_data)

        self.assertEqual(len(result), 1)

        flag = result[0]
        self.assertEqual(flag["key"], "test-flag")
        self.assertEqual(flag["name"], "Test Flag")
        self.assertEqual(flag["description"], "Test description")
        self.assertTrue(flag["enabled"])
        self.assertEqual(flag["metadata"]["provider"], "amplitude")
        self.assertEqual(flag["metadata"]["original_id"], "amplitude-123")

        # Check conditions
        self.assertEqual(len(flag["conditions"]), 1)
        condition = flag["conditions"][0]
        self.assertEqual(condition["rollout_percentage"], 100)
        self.assertEqual(condition["variant"], "variant_a")

        # Check properties
        properties = condition["properties"]
        self.assertEqual(len(properties), 1)
        self.assertEqual(properties[0]["key"], "country")
        self.assertEqual(properties[0]["operator"], "exact")
        self.assertEqual(properties[0]["value"], "US")

        # Check variants
        self.assertEqual(len(flag["variants"]), 1)
        variant = flag["variants"][0]
        self.assertEqual(variant["key"], "variant_a")
        self.assertEqual(variant["name"], "Variant A")
        self.assertEqual(variant["value"], {"color": "blue"})

    @parameterized.expand(
        [
            ("equals", "exact"),
            ("not_equals", "not_equal"),
            ("contains", "icontains"),
            ("not_contains", "not_icontains"),
            ("greater_than", "gt"),
            ("less_than", "lt"),
            ("greater_than_or_equal", "gte"),
            ("less_than_or_equal", "lte"),
            ("unknown_operator", "exact"),  # Default fallback
        ]
    )
    def test_amplitude_operator_mapping(self, amplitude_op, expected_posthog_op):
        """Test mapping of Amplitude operators to PostHog operators"""
        result = self.viewset._map_amplitude_operator(amplitude_op)
        self.assertEqual(result, expected_posthog_op)

    def test_convert_amplitude_properties(self):
        """Test _convert_amplitude_properties method"""
        amplitude_conditions = [
            {"property": "user_id", "operator": "equals", "value": "12345"},
            {"property": "plan_type", "operator": "contains", "value": "premium"},
        ]

        result = self.viewset._convert_amplitude_properties(amplitude_conditions)

        self.assertEqual(len(result), 2)

        # Check first property
        prop1 = result[0]
        self.assertEqual(prop1["key"], "user_id")
        self.assertEqual(prop1["operator"], "exact")
        self.assertEqual(prop1["value"], "12345")
        self.assertEqual(prop1["type"], "person")

        # Check second property
        prop2 = result[1]
        self.assertEqual(prop2["key"], "plan_type")
        self.assertEqual(prop2["operator"], "icontains")
        self.assertEqual(prop2["value"], "premium")
        self.assertEqual(prop2["type"], "person")

    def test_convert_to_posthog_format(self):
        """Test _convert_to_posthog_format method"""
        external_flag = {
            "key": "test-flag",
            "name": "Test Flag",
            "enabled": True,
            "conditions": [
                {
                    "properties": [{"key": "country", "operator": "exact", "value": "US", "type": "person"}],
                    "rollout_percentage": 75,
                    "variant": "variant_a",
                }
            ],
            "variants": [
                {"key": "variant_a", "name": "Variant A", "rollout_percentage": 50, "value": {"color": "blue"}}
            ],
        }

        field_mappings = {"name": "Mapped Test Flag"}

        result = self.viewset._convert_to_posthog_format(external_flag, field_mappings)

        # Check basic properties
        self.assertEqual(result["key"], "test-flag")
        self.assertEqual(result["name"], "Mapped Test Flag")  # Should use mapping
        self.assertTrue(result["active"])
        self.assertEqual(result["version"], 1)

        # Check filters structure
        filters = result["filters"]
        self.assertEqual(len(filters["groups"]), 1)

        group = filters["groups"][0]
        self.assertEqual(group["rollout_percentage"], 75)
        self.assertEqual(group["variant"], "variant_a")
        self.assertEqual(len(group["properties"]), 1)

        # Check multivariate configuration
        self.assertIn("multivariate", filters)
        self.assertEqual(len(filters["multivariate"]["variants"]), 1)

    def test_import_flags_missing_provider(self):
        """Test import flags with missing provider"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"selected_flags": [{"key": "test"}]},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and selected flags are required", response.json()["error"])

    def test_import_flags_missing_selected_flags(self):
        """Test import flags with missing selected flags"""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/", data={"provider": "amplitude"}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Provider and selected flags are required", response.json()["error"])

    def test_import_flags_successful_import(self):
        """Test successful flag import"""
        flag_data = {
            "key": "test-import",
            "name": "Test Import",
            "enabled": True,
            "conditions": [],
            "variants": [],
            "metadata": {"provider": "amplitude"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"provider": "amplitude", "selected_flags": [flag_data], "field_mappings": {}},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 0)

        # Check imported flag details
        imported_flag = data["imported_flags"][0]
        self.assertEqual(imported_flag["external_flag"]["key"], "test-import")
        self.assertEqual(imported_flag["posthog_flag"]["key"], "test-import")
        self.assertEqual(imported_flag["posthog_flag"]["name"], "Test Import")

        # Verify flag exists in database
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        db_flag = FeatureFlag.objects.get(key="test-import", team=self.team)
        self.assertEqual(db_flag.name, "Test Import")
        self.assertTrue(db_flag.active)

    def test_import_flags_conflict_handling(self):
        """Test handling of flag key conflicts during import"""
        # Create existing flag
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        FeatureFlag.objects.create(key="conflicting-flag", name="Existing Flag", team=self.team, created_by=self.user)

        flag_data = {
            "key": "conflicting-flag",
            "name": "New Flag",
            "enabled": True,
            "conditions": [],
            "variants": [],
            "metadata": {"provider": "amplitude"},
        }

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"provider": "amplitude", "selected_flags": [flag_data]},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["success_count"], 0)
        self.assertEqual(data["failure_count"], 1)

        # Check error details
        failed_import = data["failed_imports"][0]
        self.assertEqual(failed_import["flag"]["key"], "conflicting-flag")
        self.assertIn("already exists", failed_import["error"])

    def test_import_flags_partial_failure(self):
        """Test import with some successful and some failed imports"""
        # Create existing flag
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        FeatureFlag.objects.create(key="existing-flag", name="Existing Flag", team=self.team, created_by=self.user)

        flags_data = [
            {
                "key": "existing-flag",
                "name": "Conflict Flag",
                "enabled": True,
                "conditions": [],
                "variants": [],
                "metadata": {"provider": "amplitude"},
            },
            {
                "key": "new-flag",
                "name": "New Flag",
                "enabled": True,
                "conditions": [],
                "variants": [],
                "metadata": {"provider": "amplitude"},
            },
        ]

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flag_migration/import_flags/",
            data={"provider": "amplitude", "selected_flags": flags_data},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["success_count"], 1)
        self.assertEqual(data["failure_count"], 1)

        # Check successful import
        self.assertEqual(data["imported_flags"][0]["posthog_flag"]["key"], "new-flag")

        # Check failed import
        self.assertEqual(data["failed_imports"][0]["flag"]["key"], "existing-flag")
        self.assertIn("already exists", data["failed_imports"][0]["error"])
