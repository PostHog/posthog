from posthog.test.base import BaseTest

from posthog.models.feature_flag import FeatureFlag
from posthog.models.scoping import get_current_team_context, team_scope, unscoped
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


class TestBackwardsCompatibleTeamScopedQuerySet(BaseTest):
    """Tests for backwards compatible queryset that supports explicit team_id filtering."""

    def test_explicit_team_id_filter(self):
        """Verify filter(team_id=X) works as before."""
        from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedQuerySet

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        qs = BackwardsCompatibleTeamScopedQuerySet(FeatureFlag)
        filtered_qs = qs.filter(team_id=other_team.id)

        assert filtered_qs.count() == 1
        assert filtered_qs.first().key == "flag-2"

    def test_explicit_team_id_with_other_filters(self):
        """Verify filter(team_id=X, other=Y) works correctly."""
        from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedQuerySet

        FeatureFlag.objects.create(team=self.team, key="active-flag", active=True, created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="inactive-flag", active=False, created_by=self.user)

        qs = BackwardsCompatibleTeamScopedQuerySet(FeatureFlag)
        filtered_qs = qs.filter(team_id=self.team.id, active=True)

        assert filtered_qs.count() == 1
        assert filtered_qs.first().key == "active-flag"

    def test_explicit_team_id_overrides_context(self):
        """Explicit team_id in filter takes precedence over context."""
        from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedQuerySet

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        # Set context to self.team, but filter explicitly by other_team
        with team_scope(self.team.id):
            qs = BackwardsCompatibleTeamScopedQuerySet(FeatureFlag)
            # Start fresh (no context filter applied yet)
            qs = qs.unscoped()
            filtered_qs = qs.filter(team_id=other_team.id)

            assert filtered_qs.count() == 1
            assert filtered_qs.first().key == "flag-2"

    def test_unscoped_returns_correct_type(self):
        """Verify unscoped() returns BackwardsCompatibleTeamScopedQuerySet."""
        from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedQuerySet

        qs = BackwardsCompatibleTeamScopedQuerySet(FeatureFlag)
        unscoped_qs = qs.unscoped()
        assert isinstance(unscoped_qs, BackwardsCompatibleTeamScopedQuerySet)


class TestBackwardsCompatibleTeamScopedManager(BaseTest):
    """Tests for the backwards compatible manager."""

    def test_manager_filter_method(self):
        """Verify Manager.filter(team_id=X) works."""
        from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedManager

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        # Create a manager instance (normally this would be on the model)
        manager = BackwardsCompatibleTeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        filtered_qs = manager.filter(team_id=other_team.id)
        assert filtered_qs.count() == 1
        assert filtered_qs.first().key == "flag-2"

    def test_manager_unscoped_method(self):
        """Verify Manager.unscoped() returns fresh queryset."""
        from posthog.models.scoping.manager import (
            BackwardsCompatibleTeamScopedManager,
            BackwardsCompatibleTeamScopedQuerySet,
        )

        manager = BackwardsCompatibleTeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        unscoped_qs = manager.unscoped()
        assert isinstance(unscoped_qs, BackwardsCompatibleTeamScopedQuerySet)


class TestTeamFilterMixinWithCachedContext(BaseTest):
    """Tests for parent team caching in context to avoid extra queries."""

    def test_cached_parent_team_id_is_used(self):
        """When parent_team_id is in context, no extra DB query is needed."""

        # Create a child team with a parent
        parent_team = Team.objects.create(organization=self.organization, name="Parent Team")
        child_team = Team.objects.create(organization=self.organization, name="Child Team", parent_team=parent_team)

        FeatureFlag.objects.create(team=parent_team, key="parent-flag", created_by=self.user)
        FeatureFlag.objects.create(team=child_team, key="child-flag", created_by=self.user)

        # Set context with cached parent_team_id
        with team_scope(child_team.id, parent_team_id=parent_team.id):
            ctx = get_current_team_context()
            assert ctx is not None
            assert ctx.team_id == child_team.id
            assert ctx.parent_team_id == parent_team.id
            assert ctx.effective_team_id == parent_team.id

    def test_effective_team_id_without_parent(self):
        """When no parent_team_id in context, team_id is used."""
        with team_scope(self.team.id):
            ctx = get_current_team_context()
            assert ctx is not None
            assert ctx.team_id == self.team.id
            assert ctx.parent_team_id is None
            assert ctx.effective_team_id == self.team.id


class TestTeamScopedManagerIntegration(BaseTest):
    """Integration tests using real Django ORM with TeamScopedManager."""

    def test_manager_get_queryset_applies_filter_in_context(self):
        """TeamScopedManager.get_queryset() applies team filter when in context."""
        from posthog.models.scoping.manager import TeamScopedManager

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        manager = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        with team_scope(self.team.id):
            qs = manager.get_queryset()
            assert qs.count() == 1
            assert qs.first().key == "flag-1"

    def test_manager_get_queryset_no_filter_without_context(self):
        """TeamScopedManager.get_queryset() returns all when no context."""
        from posthog.models.scoping.manager import TeamScopedManager

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        manager = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        # No team scope - should return all
        qs = manager.get_queryset()
        assert qs.count() >= 2

    def test_manager_unscoped_bypasses_context(self):
        """TeamScopedManager.unscoped() ignores team context."""
        from posthog.models.scoping.manager import TeamScopedManager

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        manager = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        with team_scope(self.team.id):
            unscoped_qs = manager.unscoped()
            assert unscoped_qs.count() >= 2

    def test_queryset_chaining_preserves_team_filter(self):
        """QuerySet chaining preserves the team filter."""
        from posthog.models.scoping.manager import TeamScopedManager

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="active-flag", active=True, created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="inactive-flag", active=False, created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="other-active", active=True, created_by=self.user)

        manager = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"

        with team_scope(self.team.id):
            # Filter by active status - should only get the one from self.team
            qs = manager.get_queryset().filter(active=True)
            assert qs.count() == 1
            assert qs.first().key == "active-flag"
