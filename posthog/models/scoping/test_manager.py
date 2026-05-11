import pytest
from posthog.test.base import BaseTest

from posthog.models.feature_flag import FeatureFlag
from posthog.models.scoping import team_scope, unscoped
from posthog.models.scoping.manager import TeamScopedManager, TeamScopeError
from posthog.models.team import Team


class TestTeamScopedManager(BaseTest):
    def _make_manager(self) -> TeamScopedManager[FeatureFlag]:
        manager: TeamScopedManager[FeatureFlag] = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"
        return manager

    def test_no_scope_raises_team_scope_error(self):
        with pytest.raises(TeamScopeError, match="No team context set"):
            self._make_manager().get_queryset()

    def test_team_scope_filters_to_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        with team_scope(self.team.id):
            qs = self._make_manager().get_queryset()
            assert qs.count() == 1
            flag = qs.first()
            assert flag is not None
            assert flag.key == "flag-1"

    def test_unscoped_bypasses_context(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        with team_scope(self.team.id):
            assert self._make_manager().unscoped().count() >= 2

    def test_unscoped_works_without_context(self):
        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        assert self._make_manager().unscoped().count() >= 1

    def test_for_team_explicit_scoping(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        qs = self._make_manager().for_team(other_team.id)
        assert qs.count() == 1
        flag = qs.first()
        assert flag is not None
        assert flag.key == "flag-2"

    def test_queryset_chaining_preserves_team_filter(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="active-flag", active=True, created_by=self.user)
        FeatureFlag.objects.create(team=self.team, key="inactive-flag", active=False, created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="other-active", active=True, created_by=self.user)

        with team_scope(self.team.id):
            qs = self._make_manager().get_queryset().filter(active=True)
            assert qs.count() == 1
            flag = qs.first()
            assert flag is not None
            assert flag.key == "active-flag"

    def test_unscoped_context_clears_team(self):
        with team_scope(self.team.id):
            from posthog.models.scoping import get_current_team_id

            assert get_current_team_id() == self.team.id

            with unscoped():
                assert get_current_team_id() is None

            assert get_current_team_id() == self.team.id


class TestTeamScopedQuerySet(BaseTest):
    def test_queryset_unscoped_returns_fresh_queryset(self):
        from posthog.models.scoping.manager import TeamScopedQuerySet

        qs: TeamScopedQuerySet[FeatureFlag] = TeamScopedQuerySet(FeatureFlag)
        unscoped_qs = qs.unscoped()
        assert isinstance(unscoped_qs, TeamScopedQuerySet)

    def test_apply_team_filter(self):
        from posthog.models.scoping.manager import TeamScopedQuerySet

        other_team = Team.objects.create(organization=self.organization, name="Other Team")

        FeatureFlag.objects.create(team=self.team, key="flag-1", created_by=self.user)
        FeatureFlag.objects.create(team=other_team, key="flag-2", created_by=self.user)

        qs: TeamScopedQuerySet[FeatureFlag] = TeamScopedQuerySet(FeatureFlag)
        filtered_qs = qs._apply_team_filter(self.team.id)

        assert filtered_qs.count() == 1
        flag = filtered_qs.first()
        assert flag is not None
        assert flag.key == "flag-1"


class TestApplyTeamFilterAgainstRows(BaseTest):
    """Behavioral coverage for _apply_team_filter against real rows.

    Contract: ctx.team_id is the canonical team_id (parent if the team is
    a child env, the team's own id otherwise). The manager just filters by
    it, no resolution at read time. Callers (DRF mixin, save() rewrite, the
    `resolve_effective_team_id` helper) keep that contract.
    """

    def _make_manager(self) -> TeamScopedManager[FeatureFlag]:
        manager: TeamScopedManager[FeatureFlag] = TeamScopedManager()
        manager.model = FeatureFlag
        manager._db = "default"
        return manager

    def test_filters_by_canonical_team_id_in_context(self):
        # Caller puts canonical (parent) id in context — manager just filters.
        parent = Team.objects.create(organization=self.organization, name="Parent")
        child = Team.objects.create(organization=self.organization, name="Child", parent_team=parent)
        FeatureFlag.objects.create(team=parent, key="parent-flag", created_by=self.user)
        # FeatureFlag.save() (RootTeamMixin) rewrites team→parent on save, so child-team
        # writes land at parent. Force a stray child row to verify the filter excludes it.
        child_flag = FeatureFlag.objects.create(team=child, key="child-flag", created_by=self.user)
        FeatureFlag.objects.filter(pk=child_flag.pk).update(team_id=child.id)

        with team_scope(parent.id):
            keys = set(self._make_manager().get_queryset().values_list("key", flat=True))

        assert keys == {"parent-flag"}

    def test_root_team_filters_to_own_rows(self):
        # Root team: canonical id is the team's own id (no parent).
        FeatureFlag.objects.create(team=self.team, key="root-flag", created_by=self.user)

        with team_scope(self.team.id):
            keys = set(self._make_manager().get_queryset().values_list("key", flat=True))

        assert keys == {"root-flag"}
