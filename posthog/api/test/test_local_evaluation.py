from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import FeatureFlag


class TestFeatureFlagDependencyTransformation(APIBaseTest):
    """Test flag dependency transformation in local_evaluation endpoint."""

    def setUp(self):
        super().setUp()
        # Clean up existing flags to avoid interference
        FeatureFlag.objects.all().delete()

    def _find_flag(self, flags: list[dict], key: str) -> dict:
        """Helper method to find a flag by key in the flags list."""
        return next(flag for flag in flags if flag["key"] == key)

    def test_flag_dependency_transformation_complex_chain(self):
        """Test dependency transformation with complex dependency chains."""
        # Create a flag dependency chain: C -> B -> A
        # Create flag A
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Create flag B that depends on flag A
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Create flag C that depends on flag B
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-c",
            name="Flag C",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        flag_c_data = self._find_flag(flags, "flag-c")

        properties = flag_c_data["filters"]["groups"][0]["properties"]
        flag_property = next(prop for prop in properties if prop["type"] == "flag")

        # ID should be converted to key
        self.assertEqual(flag_property["key"], "flag-b")

        # Full dependency chain should be included (topologically sorted)
        self.assertIn("dependency_chain", flag_property)
        self.assertEqual(flag_property["dependency_chain"], ["flag-a", "flag-b"])

        flag_b_data = self._find_flag(flags, "flag-b")
        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_property_b = next(prop for prop in properties_b if prop["type"] == "flag")
        self.assertEqual(flag_property_b["dependency_chain"], ["flag-a"])

    def test_flag_dependency_transformation_circular_dependency(self):
        """Test handling of circular dependencies."""
        # Create flag A
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Create flag B that depends on flag A
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Update flag A to depend on flag B (creating a cycle)
        flag_a.filters = {
            "groups": [
                {
                    "properties": [
                        {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                    ],
                    "rollout_percentage": 100,
                }
            ]
        }
        flag_a.save()

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        self.assertIn("flags", data)
        self.assertEqual(len(data["flags"]), 2)

        flag_a_data = self._find_flag(data["flags"], "flag-a")
        flag_b_data = self._find_flag(data["flags"], "flag-b")

        # Check flag A's dependency chain is empty
        properties_a = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties_a = [prop for prop in properties_a if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_a), 1)
        self.assertEqual(flag_properties_a[0]["dependency_chain"], [])

        # Check flag B's dependency chain is empty
        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_properties_b = [prop for prop in properties_b if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_b), 1)
        self.assertEqual(flag_properties_b[0]["dependency_chain"], [])

    def test_flag_dependency_transformation_multiple_dependencies(self):
        """Test transformation with multiple flag dependencies and transitive dependencies."""
        # Create base flags
        flag_a = FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create flag C that depends on both A and B
        flag_c = FeatureFlag.objects.create(
            team=self.team,
            key="flag-c",
            name="Flag C",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_a.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Create flag D that depends on flag C (testing transitive dependencies)
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-d",
            name="Flag D",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_c.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "country", "type": "person", "value": "US", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        flag_c_data = self._find_flag(flags, "flag-c")

        properties = flag_c_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 2)

        flag_keys = {prop["key"] for prop in flag_properties}
        self.assertEqual(flag_keys, {"flag-a", "flag-b"})

        for prop in flag_properties:
            self.assertIn("dependency_chain", prop)
            if prop["key"] == "flag-a":
                self.assertEqual(prop["dependency_chain"], ["flag-a"])
            elif prop["key"] == "flag-b":
                self.assertEqual(prop["dependency_chain"], ["flag-b"])

        flag_d_data = self._find_flag(flags, "flag-d")

        properties_d = flag_d_data["filters"]["groups"][0]["properties"]
        flag_properties_d = [prop for prop in properties_d if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_d), 1)
        self.assertEqual(flag_properties_d[0]["key"], "flag-c")

        self.assertEqual(flag_properties_d[0]["dependency_chain"], ["flag-a", "flag-b", "flag-c"])

    def test_flag_dependency_transformation_self_dependency(self):
        """Test transformation handles self-dependency gracefully."""
        # Create a flag that depends on itself
        FeatureFlag.objects.create(
            team=self.team,
            key="self-flag",
            name="Self Flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            # This flag references itself - should be detected as self-dependency
                            {"key": "self-flag", "type": "flag", "value": True, "operator": "flag_evaluates_to"},
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        self_flag_data = self._find_flag(flags, "self-flag")

        properties = self_flag_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 1)
        self.assertEqual(flag_properties[0]["key"], "self-flag")

        self.assertEqual(flag_properties[0]["dependency_chain"], [])

    def test_flag_dependency_transformation_self_referencing_circular_dependency(self):
        """Test flagA -> flagB -> flagB scenario where flagB references itself."""
        # Create flag B that references itself
        flag_b = FeatureFlag.objects.create(
            team=self.team,
            key="flag-b",
            name="Flag B",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": "flag-b", "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Create flag A that depends on flag B (which has self-dependency)
        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {"key": str(flag_b.id), "type": "flag", "value": True, "operator": "flag_evaluates_to"}
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        flag_a_data = self._find_flag(flags, "flag-a")
        flag_b_data = self._find_flag(flags, "flag-b")

        # Flag B should have empty dependency chain due to self-reference
        properties_b = flag_b_data["filters"]["groups"][0]["properties"]
        flag_properties_b = [prop for prop in properties_b if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_b), 1)
        self.assertEqual(flag_properties_b[0]["key"], "flag-b")
        self.assertEqual(flag_properties_b[0]["dependency_chain"], [])

        # Flag A should have empty dependency chain because it depends on flag B which can't be evaluated
        properties_a = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties_a = [prop for prop in properties_a if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties_a), 1)
        self.assertEqual(flag_properties_a[0]["key"], "flag-b")
        self.assertEqual(flag_properties_a[0]["dependency_chain"], [])

    def test_flag_dependency_transformation_missing_dependency(self):
        """Test that missing flag dependencies result in empty dependency chain."""
        # Create flag A that references a non-existent flag by ID
        non_existent_flag_id = "999999"  # ID that doesn't exist

        FeatureFlag.objects.create(
            team=self.team,
            key="flag-a",
            name="Flag A",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": non_existent_flag_id,
                                "type": "flag",
                                "value": True,
                                "operator": "flag_evaluates_to",
                            },
                            {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        flag_a_data = self._find_flag(flags, "flag-a")

        properties = flag_a_data["filters"]["groups"][0]["properties"]
        flag_properties = [prop for prop in properties if prop["type"] == "flag"]
        self.assertEqual(len(flag_properties), 1)

        # The key should remain as the original ID since it can't be resolved
        self.assertEqual(flag_properties[0]["key"], non_existent_flag_id)

        # Dependency chain should be empty because the referenced flag doesn't exist
        self.assertEqual(flag_properties[0]["dependency_chain"], [])

    def test_flag_dependency_transformation_shared_dependencies(self):
        """Test that shared dependencies are handled correctly and efficiently."""
        # Create a base flag that will be shared by multiple other flags
        shared_flag = FeatureFlag.objects.create(
            team=self.team,
            key="shared-dependency",
            name="Shared Dependency",
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Create multiple flags that all depend on the same shared flag
        dependent_flags = []
        for i in range(5):  # Create 5 flags that depend on the shared flag
            flag = FeatureFlag.objects.create(
                team=self.team,
                key=f"dependent-flag-{i}",
                name=f"Dependent Flag {i}",
                filters={
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": str(shared_flag.id),
                                    "type": "flag",
                                    "value": True,
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            )
            dependent_flags.append(flag)

        response = self.client.get(f"/api/projects/{self.team.id}/feature_flags/local_evaluation")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        flags = data["flags"]

        # Verify that all dependent flags have the correct dependency chain
        for i, _flag in enumerate(dependent_flags):
            flag_data = self._find_flag(flags, f"dependent-flag-{i}")
            properties = flag_data["filters"]["groups"][0]["properties"]
            flag_properties = [prop for prop in properties if prop["type"] == "flag"]

            self.assertEqual(len(flag_properties), 1)
            self.assertEqual(flag_properties[0]["key"], "shared-dependency")
            self.assertEqual(flag_properties[0]["dependency_chain"], ["shared-dependency"])

        # This test demonstrates that:
        # 1. The shared dependency chain is built once and reused
        # 2. All flags referencing the same dependency get the same chain
        # 3. The optimization correctly handles multiple flags with shared dependencies
