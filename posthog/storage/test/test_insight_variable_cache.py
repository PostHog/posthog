from django.core.cache import cache
from django.test import TestCase

from parameterized import parameterized

import posthog.storage.insight_variable_cache_signal_handlers  # noqa: F401 — registers signal receivers
from posthog.models.insight_variable import InsightVariable
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.storage.insight_variable_cache import (
    _cache_key,
    get_insight_variables_for_team,
    invalidate_insight_variables_for_team,
)


class TestInsightVariableCache(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def test_get_loads_from_db_on_miss_and_caches(self):
        InsightVariable.objects.create(team=self.team, name="Var A", code_name="var_a", type="String")

        cache.delete(_cache_key(self.team.id))

        assert cache.get(_cache_key(self.team.id)) is None

        result = get_insight_variables_for_team(self.team.id)

        assert [v.code_name for v in result] == ["var_a"]
        assert cache.get(_cache_key(self.team.id)) is not None

    def test_get_returns_cached_value_without_db_hit(self):
        sentinel = [
            InsightVariable(team_id=self.team.id, name="From Cache", code_name="from_cache", type="String"),
        ]
        cache.set(_cache_key(self.team.id), sentinel, timeout=300)

        result = get_insight_variables_for_team(self.team.id)

        assert [v.code_name for v in result] == ["from_cache"]

    def test_get_caches_empty_list(self):
        cache.delete(_cache_key(self.team.id))

        result = get_insight_variables_for_team(self.team.id)

        assert result == []

        cached = cache.get(_cache_key(self.team.id))
        assert cached == []

    def test_invalidate_clears_cache(self):
        cache.set(_cache_key(self.team.id), ["anything"], timeout=300)

        invalidate_insight_variables_for_team(self.team.id)

        assert cache.get(_cache_key(self.team.id)) is None

    def test_cache_is_team_scoped(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        InsightVariable.objects.create(team=self.team, name="Mine", code_name="mine", type="String")
        InsightVariable.objects.create(team=other_team, name="Theirs", code_name="theirs", type="String")

        mine = get_insight_variables_for_team(self.team.id)
        theirs = get_insight_variables_for_team(other_team.id)

        assert [v.code_name for v in mine] == ["mine"]
        assert [v.code_name for v in theirs] == ["theirs"]


class TestInsightVariableCacheSignals(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    @parameterized.expand(
        [
            ("create", "after_create"),
            ("update", "after_update"),
        ]
    )
    def test_post_save_invalidates_cache(self, _name: str, scenario: str):
        # warm the cache so we can observe invalidation
        get_insight_variables_for_team(self.team.id)
        assert cache.get(_cache_key(self.team.id)) is not None

        with self.captureOnCommitCallbacks(execute=True):
            if scenario == "after_create":
                InsightVariable.objects.create(team=self.team, name="New", code_name="new", type="String")
            else:
                variable = InsightVariable.objects.create(team=self.team, name="Old", code_name="old", type="String")
                cache.set(_cache_key(self.team.id), [variable], timeout=300)
                variable.name = "Renamed"
                variable.save()

        assert cache.get(_cache_key(self.team.id)) is None

    def test_post_delete_invalidates_cache(self):
        variable = InsightVariable.objects.create(team=self.team, name="Doomed", code_name="doomed", type="String")
        get_insight_variables_for_team(self.team.id)
        assert cache.get(_cache_key(self.team.id)) is not None

        with self.captureOnCommitCallbacks(execute=True):
            variable.delete()

        assert cache.get(_cache_key(self.team.id)) is None

    def test_signal_only_invalidates_affected_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        get_insight_variables_for_team(self.team.id)
        get_insight_variables_for_team(other_team.id)
        assert cache.get(_cache_key(self.team.id)) is not None
        assert cache.get(_cache_key(other_team.id)) is not None

        with self.captureOnCommitCallbacks(execute=True):
            InsightVariable.objects.create(team=other_team, name="Only Theirs", code_name="only_theirs", type="String")

        assert cache.get(_cache_key(self.team.id)) is not None
        assert cache.get(_cache_key(other_team.id)) is None

    def test_invalidation_waits_for_commit(self):
        get_insight_variables_for_team(self.team.id)
        assert cache.get(_cache_key(self.team.id)) is not None

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            InsightVariable.objects.create(team=self.team, name="X", code_name="x", type="String")
            assert cache.get(_cache_key(self.team.id)) is not None, (
                "cache must not be invalidated before the surrounding transaction commits"
            )

        assert len(callbacks) == 1
