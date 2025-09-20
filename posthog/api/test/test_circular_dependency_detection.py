"""
Tests for circular dependency detection in feature flags.
"""

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import FeatureFlag


class TestCircularDependencyDetection(APIBaseTest):
    """Test cases for feature flag circular dependency detection."""

    def setUp(self):
        super().setUp()
        FeatureFlag.objects.filter(team=self.team).delete()

    def create_flag(self, key, name=None, dependencies=None):
        """Helper to create a flag with optional dependencies."""
        name = name or f"Flag {key.upper()}"
        properties = []
        if dependencies:
            for dep_id in dependencies:
                properties.append(
                    {
                        "key": str(dep_id),
                        "type": "flag",
                        "value": "true",
                        "operator": "flag_evaluates_to",
                    }
                )

        return FeatureFlag.objects.create(
            team=self.team,
            key=key,
            name=name,
            filters={
                "groups": [
                    {
                        "properties": properties,
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

    def update_flag_dependencies(self, flag_id, dependencies):
        """Helper to update a flag's dependencies."""
        properties = []
        for dep_id in dependencies:
            properties.append(
                {
                    "key": str(dep_id),
                    "type": "flag",
                    "value": "true",
                    "operator": "flag_evaluates_to",
                }
            )

        return self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_id}/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": properties,
                            "rollout_percentage": 100,
                        }
                    ]
                }
            },
            format="json",
        )

    def test_self_reference_detection(self):
        """Test that a flag cannot reference itself."""
        flag = self.create_flag("self_ref_flag")
        response = self.update_flag_dependencies(flag.id, [flag.id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("cannot depend on itself", response.json()["detail"])

    @parameterized.expand(
        [
            ("direct", ["flag_a", "flag_b"], "flag_a → flag_b → flag_a"),
            ("indirect", ["flag_a", "flag_b", "flag_c"], "flag_a → flag_c → flag_b → flag_a"),
        ]
    )
    def test_circular_dependency_detection(self, _name, flag_keys, expected_cycle):
        """Test detection of circular dependencies."""
        flags: list[FeatureFlag] = []

        # Create flags in a chain: A -> B -> C -> ...
        for i, key in enumerate(flag_keys):
            dependencies = [flags[i - 1].id] if i > 0 else None
            flag = self.create_flag(key, dependencies=dependencies)
            flags.append(flag)

        # Try to create cycle by making first flag depend on last
        response = self.update_flag_dependencies(flags[0].id, [flags[-1].id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        detail = response.json()["detail"]
        self.assertIn("Circular dependency detected", detail)
        self.assertIn(expected_cycle, detail)

    def test_valid_dependency_chain(self):
        """Test that valid dependency chains are allowed."""
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b", dependencies=[flag_a.id])
        flag_c = self.create_flag("flag_c", dependencies=[flag_b.id])

        # All flags should be created successfully
        self.assertIsNotNone(flag_c)

    def test_non_existent_flag_dependency(self):
        """Test that dependencies on non-existent flags are rejected."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Flag with non-existent dependency",
                "key": "flag_with_missing_dep",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "99999",
                                    "type": "flag",
                                    "value": "true",
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Flag dependency references non-existent flag", response.json()["detail"])

    def test_invalid_flag_reference_string(self):
        """Test that string flag references are rejected."""
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Flag with string dependency",
                "key": "flag_with_string_dep",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": "invalid_flag_key",
                                    "type": "flag",
                                    "value": "true",
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Flag dependencies must reference flag IDs", response.json()["detail"])

    def test_multiple_flag_dependencies_no_cycle(self):
        """Test that multiple flag dependencies without cycles are allowed."""
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b")
        flag_c = self.create_flag("flag_c", dependencies=[flag_a.id, flag_b.id])

        # Flag with multiple dependencies should be created successfully
        self.assertIsNotNone(flag_c)

    def test_complex_dependency_graph_with_cycle(self):
        """Test detection in complex dependency graph with multiple paths."""
        # Create a diamond dependency pattern: A -> B, A -> C, B -> D, C -> D
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b", dependencies=[flag_a.id])
        flag_c = self.create_flag("flag_c", dependencies=[flag_a.id])
        flag_d = self.create_flag("flag_d", dependencies=[flag_b.id, flag_c.id])

        # Try to create cycle: D -> A
        response = self.update_flag_dependencies(flag_a.id, [flag_d.id])

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Circular dependency detected", response.json()["detail"])

    def test_deleted_flag_dependencies(self):
        """Test that deleted flags are ignored in dependency resolution."""
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b", dependencies=[flag_a.id])

        # Soft delete flag A and remove dependency from flag B
        flag_a.deleted = True
        flag_a.save()
        flag_b.filters = {"groups": [{"properties": [], "rollout_percentage": 100}]}
        flag_b.save()

        # Create new flag that depends on B - should work since old dependency is gone
        new_flag = self.create_flag("new_flag_a", dependencies=[flag_b.id])
        self.assertIsNotNone(new_flag)

    def test_flag_dependency_with_mixed_properties(self):
        """Test that flag dependencies work correctly with other property types."""
        flag_a = self.create_flag("flag_a")

        # Create flag with both flag dependency and person property
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "Flag B",
                "key": "flag_b",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": str(flag_a.id),
                                    "type": "flag",
                                    "value": "true",
                                    "operator": "flag_evaluates_to",
                                },
                                {"key": "email", "type": "person", "value": "test@example.com", "operator": "exact"},
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                },
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
