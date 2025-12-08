"""
Tests for preventing deletion of feature flags that other flags depend on.
"""

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import FeatureFlag


class TestFeatureFlagDependencyDeletion(APIBaseTest):
    """Test cases for preventing deletion of flags with dependencies."""

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

    def test_cannot_delete_flag_with_active_dependents(self):
        """Test that a flag cannot be deleted if other active flags depend on it."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])

        # Try to delete base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot delete this feature flag because other flags depend on it", response.json()["detail"])
        self.assertIn(f"{dependent_flag.key} (ID: {dependent_flag.id})", response.json()["detail"])

    def test_can_delete_flag_with_no_dependents(self):
        """Test that a flag can be deleted if no other flags depend on it."""
        # Create flag with no dependents
        flag = self.create_flag("standalone_flag")

        # Should be able to delete it
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify flag is deleted
        flag.refresh_from_db()
        self.assertTrue(flag.deleted)

    def test_can_delete_flag_with_inactive_dependents(self):
        """Test that a flag can be deleted if dependent flags are inactive."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag but make it inactive
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])
        dependent_flag.active = False
        dependent_flag.save()

        # Should be able to delete base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_can_delete_flag_with_deleted_dependents(self):
        """Test that a flag can be deleted if dependent flags are already deleted."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create dependent flag but mark it as deleted
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])
        dependent_flag.deleted = True
        dependent_flag.save()

        # Should be able to delete base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_cannot_delete_flag_with_multiple_dependents(self):
        """Test error message when multiple flags depend on the flag being deleted."""
        # Create base flag
        base_flag = self.create_flag("base_flag")

        # Create multiple dependent flags
        dependent_flags = []
        for i in range(8):
            dependent_flags.append(self.create_flag(f"dependent_flag_{i}", dependencies=[base_flag.id]))

        # Try to delete base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        error_detail = response.json()["detail"]

        # Should show first 5 flags
        for i in range(5):
            self.assertIn(f"{dependent_flags[i].key} (ID: {dependent_flags[i].id})", error_detail)

        # Should indicate there are more
        self.assertIn("and 3 more", error_detail)

    def test_cannot_delete_flag_in_dependency_chain(self):
        """Test that middle flags in a dependency chain cannot be deleted."""
        # Create chain: A -> B -> C
        flag_a = self.create_flag("flag_a")
        flag_b = self.create_flag("flag_b", dependencies=[flag_a.id])
        flag_c = self.create_flag("flag_c", dependencies=[flag_b.id])

        # Try to delete flag B (middle of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_b.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"{flag_c.key} (ID: {flag_c.id})", response.json()["detail"])

        # Try to delete flag A (start of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_a.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(f"{flag_b.key} (ID: {flag_b.id})", response.json()["detail"])

        # Should be able to delete flag C (end of chain)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{flag_c.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_flag_with_mixed_properties_prevents_deletion(self):
        """Test that flags with both flag dependencies and other properties prevent deletion."""
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

        # Try to delete base flag
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
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

        # Create dependent flag in other team (this shouldn't affect deletion)
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

        # Should be able to delete base flag (other team's dependency shouldn't matter)
        response = self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/",
            {"deleted": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_has_active_dependents_with_no_dependencies(self):
        """Test has_active_dependents returns False with 0 dependent flags."""
        flag = self.create_flag("standalone_flag")

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{flag.id}/has_active_dependents/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["has_active_dependents"], False)
        self.assertEqual(len(response.json()["dependent_flags"]), 0)

    def test_has_active_dependents_with_active_dependencies(self):
        """Test has_active_dependents returns True with 1 active dependent flag."""
        base_flag = self.create_flag("base_flag")
        self.create_flag("dependent_flag", dependencies=[base_flag.id])

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/has_active_dependents/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["has_active_dependents"], True)
        self.assertEqual(len(response.json()["dependent_flags"]), 1)

    def test_has_active_dependents_with_inactive_dependencies(self):
        """Test has_active_dependents returns False when dependent flags are inactive."""
        base_flag = self.create_flag("base_flag")
        dependent_flag = self.create_flag("dependent_flag", dependencies=[base_flag.id])
        dependent_flag.active = False
        dependent_flag.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/{base_flag.id}/has_active_dependents/",
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["has_active_dependents"], False)
        self.assertEqual(len(response.json()["dependent_flags"]), 0)
