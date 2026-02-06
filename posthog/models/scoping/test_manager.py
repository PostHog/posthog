from posthog.test.base import BaseTest

from posthog.models.feature_flag import FeatureFlag
from posthog.models.scoping import team_scope, unscoped
from posthog.models.team import Team


class TestTeamScopedManager(BaseTest):
    """Tests for automatic team scoping behavior."""

    def test_no_scope_returns_all_results(self):
        """Without team scope, queries return all results (no automatic filtering)."""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        # Without scope, we get all flags (current behavior, manager applies no filter)
        # Note: This test documents current behavior - once we migrate FeatureFlag
        # to use TeamScopedManager, this will change
        all_flags = FeatureFlag.objects.all()
        assert all_flags.count() >= 2

    def test_team_scope_filters_to_team(self):
        """With team_scope context, queries are filtered to that team."""
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        flag1 = FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        # This test uses the scoping module directly to demonstrate behavior
        # Once FeatureFlag uses TeamScopedManager, this will work automatically
        with team_scope(self.team.id):
            from posthog.models.scoping import get_current_team_id

            assert get_current_team_id() == self.team.id

            # For now, just verify the context is set correctly
            # Full integration test will come when we migrate FeatureFlag
            assert flag1.team_id == self.team.id

    def test_unscoped_context_clears_team(self):
        """The unscoped() context manager clears the team filter."""
        with team_scope(self.team.id):
            from posthog.models.scoping import get_current_team_id

            assert get_current_team_id() == self.team.id

            with unscoped():
                assert get_current_team_id() is None

            # Restored after exiting unscoped
            assert get_current_team_id() == self.team.id


class TestTeamScopedQuerySet(BaseTest):
    """Tests for the QuerySet's unscoped() method."""

    def test_queryset_unscoped_method_exists(self):
        """Verify unscoped() method is available on queryset."""
        from posthog.models.scoping.manager import TeamScopedQuerySet

        qs = TeamScopedQuerySet(FeatureFlag)
        unscoped_qs = qs.unscoped()
        assert isinstance(unscoped_qs, TeamScopedQuerySet)

    def test_apply_team_filter(self):
        """Verify _apply_team_filter adds the correct filter."""
        from posthog.models.scoping.manager import TeamScopedQuerySet

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        qs = TeamScopedQuerySet(FeatureFlag)
        filtered_qs = qs._apply_team_filter(self.team.id)

        # Should only return the flag from self.team
        assert filtered_qs.count() == 1
        assert filtered_qs.first().key == "flag-1"
