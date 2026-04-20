"""
Tests for preventing disabling of feature flags that other flags depend on.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import FeatureFlag


class TestFeatureFlagDependencyDisabling(APIBaseTest):
    """Test cases for preventing disabling of flags with dependencies."""

    def setUp(self):
        super().setUp()
        FeatureFlag.objects.filter(team=self.team).delete()

    def create_flag(self, key, name=None, dependencies=None, active=True):
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
            active=active,
            filters={
                "groups": [
                    {
                        "properties": properties,
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

    def test_cannot_disable_flag_with_active_dependents(self):
        """Test that a flag cannot be disabled if other active flags depend on it."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])

        # Try to disable base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot disable this feature flag because other flags depend on it", response.json()["detail"])
        self.assertIn(f"{dependent_flag.key} (ID: {dependent_flag.id})", response.json()["detail"])

    def test_can_disable_flag_with_no_dependents(self):
        """Test that a flag can be disabled if no other flags depend on it."""
        # Create flag with no dependents
        flag = self.create_flag("standalone_flag")

        # Should be able to disable it
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify flag is disabled
        flag.refresh_from_db()
        self.assertFalse(flag.active)

    def test_can_disable_flag_with_inactive_dependents(self):
        """Test that a flag can be disabled if dependent flags are inactive."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag but make it inactive
        self.create_flag("dependent_flag", dependencies=[base_flag.id], active=False)

        # Should be able to disable base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_can_disable_flag_with_deleted_dependents(self):
        """Test that a flag can be disabled if dependent flags are already deleted."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag but mark it as deleted
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])
        dependent_flag.deleted = True
        dependent_flag.save()

        # Should be able to disable base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_disable_flag_with_multiple_dependents(self):
        """Test error message when multiple flags depend on the flag being disabled."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create multiple dependent flags
        dependent_flags = []
        for i in range(8):
            dependent_flags.append(self.create_flag(f"dependent_flag_{i}", dependencies=[base_flag.id]))

        # Try to disable base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = response.json()["detail"]

        # Should show first 5 flags
        for i in range(5):
            self.assertIn(f"{dependent_flags[i].key} (ID: {dependent_flags[i].id})", error_detail)

        # Should indicate there are more
        self.assertIn("and 3 more", error_detail)

    def test_cannot_disable_flag_in_dependency_chain(self):
        """Test that middle flags in a dependency chain cannot be disabled."""
        # Create chain: A -> B -> C
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b", dependencies=[flag_a.id])
        flag_c = self.create_flag("flag_c", dependencies=[flag_b.id])

        # Try to disable flag B (middle of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_b.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"{flag_c.key} (ID: {flag_c.id})", response.json()["detail"])

        # Try to disable flag A (start of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_a.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"{flag_b.key} (ID: {flag_b.id})", response.json()["detail"])

        # Should be able to disable flag C (end of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_c.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_flag_with_mixed_properties_prevents_disabling(self):
        """Test that flags with both flag dependencies and other properties prevent disabling."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create flag with both flag dependency and person property
        dependent_flag = FeatureFlag.objects.create(
            team=self.team,
            key="mixed_flag",
            name="Mixed Flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": str(base_flag.id),
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
        )

        # Try to disable base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"{dependent_flag.key} (ID: {dependent_flag.id})", response.json()["detail"])

    def test_dependency_check_only_within_same_team(self):
        """Test that dependency checks are scoped to the same team."""
        # Create base flag in current team
        base_flag = self.create_flag("base_flag")

        # Create a new team
        other_team = self.organization.teams.create(name="Other Team")

        # Create dependent flag in other team (this shouldn't affect disabling)
        FeatureFlag.objects.create(
            team=other_team,
            key="other_team_flag",
            name="Other Team Flag",
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": str(base_flag.id),  # References base_flag but in different team
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            }
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Should be able to disable base flag (other team's dependency shouldn't matter)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_can_enable_flag_that_was_previously_disabled(self):
        """Test that a flag can be re-enabled after being disabled."""
        # Create base flag
        base_flag = self.create_flag("base_flag", active=False)

        # Create dependent flag
        self.create_flag("dependent_flag", dependencies=[base_flag.id])

        # Should be able to enable base flag (no check on enabling)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify flag is enabled
        base_flag.refresh_from_db()
        self.assertTrue(base_flag.active)

    def test_disabling_already_disabled_flag_no_error(self):
        """Test that disabling an already disabled flag doesn't trigger dependency check."""
        # Create base flag that's already disabled
        base_flag = self.create_flag("base_flag", active=False)

        # Create dependent flag
        self.create_flag("dependent_flag", dependencies=[base_flag.id])

        # Should be able to "disable" already disabled flag (no-op)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_enable_dependent_flag_when_dependency_disabled(self):
        """Test that dependent flags cannot be enabled when their dependencies are disabled."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag that's initially inactive
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id], active=False)

        # Disable the base flag (should work since dependent is inactive)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"active": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify base flag is disabled
        base_flag.refresh_from_db()
        self.assertFalse(base_flag.active)

        # Should NOT be able to enable dependent flag when its dependency is disabled
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{dependent_flag.id}/",
            {"active": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot enable this feature flag because it depends on disabled flags", response.json()["detail"])
        self.assertIn(f"{base_flag.key} (ID: {base_flag.id})", response.json()["detail"])

        # Verify dependent flag is still disabled
        dependent_flag.refresh_from_db()
        self.assertFalse(dependent_flag.active)

    def test_cannot_enable_flag_with_multiple_disabled_dependencies(self):
        """Test error message when trying to enable flag with multiple disabled dependencies."""
        # Create base flags
        flag_a = self.create_flag("flag_a", active=False)
        flag_b = self.create_flag("flag_b", active=False)
        flag_c = self.create_flag("flag_c")  # This one is active

        # Create dependent flag that depends on all three
        dependent_flag = FeatureFlag.objects.create(
            team=self.team,
            key="dependent_flag",
            name="Dependent Flag",
            active=False,
            filters={
                "groups": [
                    {
                        "properties": [
                            {
                                "key": str(flag_a.id),
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            },
                            {
                                "key": str(flag_b.id),
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            },
                            {
                                "key": str(flag_c.id),
                                "type": "flag",
                                "value": "true",
                                "operator": "flag_evaluates_to",
                            },
                        ],
                        "rollout_percentage": 100,
                    }
                ]
            },
        )

        # Try to enable dependent flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{dependent_flag.id}/",
            {"active": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = response.json()["detail"]

        # Should mention both disabled flags
        self.assertIn(f"{flag_a.key} (ID: {flag_a.id})", error_detail)
        self.assertIn(f"{flag_b.key} (ID: {flag_b.id})", error_detail)
        # Should NOT mention the active flag
        self.assertNotIn(f"{flag_c.key} (ID: {flag_c.id})", error_detail)

    def test_cannot_create_dependency_on_disabled_flag(self):
        """Test that creating a dependency on a disabled flag is prevented."""
        # Create a disabled flag
        disabled_flag = self.create_flag("disabled_flag", active=False)

        # Try to create a new flag that depends on the disabled flag
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/",
            {
                "name": "New Flag",
                "key": "new_flag",
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": str(disabled_flag.id),
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
        error_detail = response.json()["detail"]
        self.assertIn(f"Cannot create dependency on disabled flag '{disabled_flag.key}'", error_detail)
        self.assertIn(f"ID: {disabled_flag.id}", error_detail)

    def test_cannot_update_flag_to_add_dependency_on_disabled_flag(self):
        """Test that updating a flag to add a dependency on a disabled flag is prevented."""
        # Create an active flag and a disabled flag
        active_flag = self.create_flag("active_flag")
        disabled_flag = self.create_flag("disabled_flag", active=False)

        # Try to update the active flag to depend on the disabled flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{active_flag.id}/",
            {
                "filters": {
                    "groups": [
                        {
                            "properties": [
                                {
                                    "key": str(disabled_flag.id),
                                    "type": "flag",
                                    "value": "true",
                                    "operator": "flag_evaluates_to",
                                }
                            ],
                            "rollout_percentage": 100,
                        }
                    ]
                }
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = response.json()["detail"]
        self.assertIn(f"Cannot create dependency on disabled flag '{disabled_flag.key}'", error_detail)
        self.assertIn(f"ID: {disabled_flag.id}", error_detail)
