from posthog.test.base import BaseTest
from pytest import fixture
from unittest import mock

from django.core.cache import cache

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Cohort
from posthog.models.cohort.dependencies import (
    COHORT_DEPENDENCY_CACHE_COUNTER,
    DEPENDENCY_CACHE_TIMEOUT,
    extract_cohort_dependencies,
    get_cohort_dependencies,
    get_cohort_dependents,
    warm_team_cohort_dependency_cache,
)


class TestCohortDependencies(BaseTest):
    def _create_cohort(self, name: str, **kwargs):
        return Cohort.objects.create(name=name, team=self.team, **kwargs)

    def _assert_depends_on(self, dependent_cohort: Cohort, dependency_cohort: Cohort) -> None:
        self.assertEqual(cache.get(f"cohort:dependencies:{dependent_cohort.id}"), [dependency_cohort.id])
        self.assertEqual(cache.get(f"cohort:dependents:{dependency_cohort.id}"), [dependent_cohort.id])
        self.assertEqual(list(get_cohort_dependencies(dependent_cohort)), [dependency_cohort.id])
        self.assertEqual(list(get_cohort_dependents(dependency_cohort)), [dependent_cohort.id])

    def _assert_cohorts_have_no_relationships(self, *cohorts: Cohort) -> None:
        for cohort in cohorts:
            self.assertEqual(len(get_cohort_dependencies(cohort)), 0, f"Expected no dependencies for {cohort.name}")
            self.assertEqual(len(get_cohort_dependents(cohort)), 0, f"Expected no dependents for {cohort.name}")

    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @fixture(autouse=True)
    def mock_transaction(self):
        with mock.patch("django.db.transaction.on_commit", side_effect=lambda func: func()):
            yield

    def test_cohort_dependency_created(self) -> None:
        """
        When a new cohort is created including a property that references another cohort,
        a dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohort_dependency_updated(self) -> None:
        """
        When a cohort's properties are updated to add a dependency, the dependency should be created.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(name="Test Cohort B")

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

        cohort_b.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        cohort_b.save()

        self._assert_depends_on(cohort_b, cohort_a)

    def test_cohorts_dependency_updated_delete(self) -> None:
        """
        When a cohort's properties are updated to remove a dependency, the dependency should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.groups = [{"properties": {}}]
        cohort_b.save()

        self._assert_cohorts_have_no_relationships(cohort_a, cohort_b)

    def test_cohort_dependency_updated_changed(self) -> None:
        """
        When a cohort's properties are updated to change a dependency, the dependency should be updated.
        """
        cohort_a = self._create_cohort(name="Test Cohort A", groups=[])
        cohort_b = self._create_cohort(name="Test Cohort B", groups=[])
        cohort_c = self._create_cohort(
            name="Test Cohort C", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_c, cohort_a)
        self._assert_cohorts_have_no_relationships(cohort_b)
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), [cohort_c.id])
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_b.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_b.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_c.id}"), [cohort_a.id])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_c.id}"), [])

        cohort_c.groups = [{"properties": [{"key": "id", "type": "cohort", "value": cohort_b.id}]}]
        cohort_c.save()

        self._assert_depends_on(cohort_c, cohort_b)
        self._assert_cohorts_have_no_relationships(cohort_a)
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_b.id}"), [])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_b.id}"), [cohort_c.id])
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_c.id}"), [cohort_b.id])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_c.id}"), [])

    def test_cohort_dependency_deleted(self) -> None:
        """
        When a cohort is deleted, its dependencies should be removed.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_b.delete()

        self._assert_cohorts_have_no_relationships(cohort_a)

    def test_cohort_soft_delete(self) -> None:
        """
        When a cohort is soft deleted, its dependencies are be retained, though its dependencies
        are not cached.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        cohort_a.deleted = True
        cohort_a.save()

        # The dependency is still intact via Cohort B's props
        # You must filter out deleted cohorts
        self._assert_depends_on(cohort_b, cohort_a)

        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), [cohort_b.id])

    def test_cohort_team_deleted(self) -> None:
        """
        When a team is deleted, its cohorts should be deleted.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        self._assert_depends_on(cohort_b, cohort_a)

        self.team.delete()

        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_b.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_b.id}"), None)

    def test_warm_team_cohort_dependency_cache(self) -> None:
        """
        When a team is warmed up, its cohorts should have their dependencies cached.
        """
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_b.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_b.id}"), None)

        warm_team_cohort_dependency_cache(self.team.id)

        self._assert_depends_on(cohort_b, cohort_a)

    @parameterized.expand(
        [
            (1,),  # Process one cohort at a time
            (2,),  # Process two cohorts at a time
            (5,),  # Process five cohorts at a time
            (100,),  # Process more than the number of cohorts
        ]
    )
    def test_warm_team_cohort_dependency_cache_batching(self, batch_size: int) -> None:
        cohorts: list[Cohort] = []
        for i in range(5):
            if i == 0:
                cohort = self._create_cohort(name=f"Base Cohort {i}")
            else:
                cohort = self._create_cohort(
                    name=f"Dependent Cohort {i}",
                    groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohorts[i - 1].id}]}],
                )
            cohorts.append(cohort)

        cache.clear()

        for cohort in cohorts:
            self.assertEqual(cache.get(f"cohort:dependencies:{cohort.id}"), None)
            self.assertEqual(cache.get(f"cohort:dependents:{cohort.id}"), None)

        warm_team_cohort_dependency_cache(self.team.id, batch_size=batch_size)

        for i, cohort in enumerate(cohorts):
            if i == 0:
                self.assertEqual(cache.get(f"cohort:dependencies:{cohort.id}"), [])
                self.assertEqual(cache.get(f"cohort:dependents:{cohort.id}"), [cohorts[1].id])
            elif i == len(cohorts) - 1:
                self.assertEqual(cache.get(f"cohort:dependencies:{cohort.id}"), [cohorts[i - 1].id])
                self.assertEqual(cache.get(f"cohort:dependents:{cohort.id}"), [])
            else:
                self.assertEqual(cache.get(f"cohort:dependencies:{cohort.id}"), [cohorts[i - 1].id])
                self.assertEqual(cache.get(f"cohort:dependents:{cohort.id}"), [cohorts[i + 1].id])

    def test_warm_team_cohort_dependency_cache_refreshes_ttl(self) -> None:
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        # Warm the cache initially
        warm_team_cohort_dependency_cache(self.team.id)

        # Mock cache.touch and cache.set_many to verify TTL refresh
        with mock.patch.object(cache, "touch") as mock_touch, mock.patch.object(cache, "set_many") as mock_set_many:
            # Call warm again - should refresh TTL
            warm_team_cohort_dependency_cache(self.team.id)

            # Verify touch was called for dependency keys
            expected_dependency_keys = [
                f"cohort:dependencies:{cohort_a.id}",
                f"cohort:dependencies:{cohort_b.id}",
            ]

            for key in expected_dependency_keys:
                mock_touch.assert_any_call(key, timeout=DEPENDENCY_CACHE_TIMEOUT)

            # Verify set_many was called with timeout for dependents
            self.assertTrue(mock_set_many.called)
            args, kwargs = mock_set_many.call_args
            self.assertEqual(kwargs.get("timeout"), DEPENDENCY_CACHE_TIMEOUT)

    def test_cache_miss_get_cohort_dependencies(self) -> None:
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()

        self.assertEqual(get_cohort_dependencies(cohort_b), [cohort_a.id])

        # get_cohort_dependencies is cheap - it doesn't need to warm the entire cache
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependencies:{cohort_b.id}"), [cohort_a.id])
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_a.id}"), None)
        self.assertEqual(cache.get(f"cohort:dependents:{cohort_b.id}"), None)

    def test_cache_miss_get_cohort_dependents(self) -> None:
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()

        self.assertEqual(get_cohort_dependents(cohort_a), [cohort_b.id])

        # get_cohort_dependents is a more expensive cache miss, it warms the entire cache because
        # it has to iterate all cohorts in the team
        self._assert_depends_on(cohort_b, cohort_a)

    def test_cache_miss_get_cohort_dependent_int_param(self) -> None:
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()

        self.assertEqual(get_cohort_dependents(cohort_a.id), [cohort_b.id])
        self._assert_depends_on(cohort_b, cohort_a)

    @parameterized.expand(
        [
            ("dependencies",),
            ("dependents",),
        ]
    )
    def test_cache_hit_counters(self, cache_type: str):
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        # Warm the cache first
        warm_team_cohort_dependency_cache(self.team.id)

        # Get initial counter values
        initial_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type=cache_type, result="hit")._value._value

        if cache_type == "dependencies":
            get_cohort_dependencies(cohort_b)
        else:
            get_cohort_dependents(cohort_a)

        # Verify hit counter incremented
        final_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type=cache_type, result="hit")._value._value
        self.assertEqual(final_hits, initial_hits + 1)

    @parameterized.expand(
        [
            ("dependencies",),
            ("dependents",),
        ]
    )
    def test_cache_miss_counters(self, cache_type: str):
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        # Clear cache to ensure miss
        cache.clear()

        # Get initial counter values
        initial_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type=cache_type, result="miss")._value._value

        if cache_type == "dependencies":
            get_cohort_dependencies(cohort_b)
        else:
            get_cohort_dependents(cohort_a)

        # Verify miss counter incremented
        final_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type=cache_type, result="miss")._value._value
        self.assertEqual(final_misses, initial_misses + 1)

    def test_cache_hit_miss_sequence(self):
        cohort_a = self._create_cohort(name="Test Cohort A")
        cohort_b = self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()

        # Get initial counter values
        dep_initial_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="hit")._value._value
        dep_initial_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependencies", result="miss"
        )._value._value
        dept_initial_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="hit")._value._value
        dept_initial_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependents", result="miss"
        )._value._value

        # First call should be a miss
        get_cohort_dependencies(cohort_b)
        dep_after_first = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="miss")._value._value
        self.assertEqual(dep_after_first, dep_initial_misses + 1)

        # Second call should be a hit
        get_cohort_dependencies(cohort_b)
        dep_hits_after_second = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependencies", result="hit"
        )._value._value
        self.assertEqual(dep_hits_after_second, dep_initial_hits + 1)

        # First dependents call should be a miss (and warms cache)
        get_cohort_dependents(cohort_a)
        dept_after_first = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependents", result="miss")._value._value
        self.assertEqual(dept_after_first, dept_initial_misses + 1)

        # Second dependents call should be a hit
        get_cohort_dependents(cohort_a)
        dept_hits_after_second = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependents", result="hit"
        )._value._value
        self.assertEqual(dept_hits_after_second, dept_initial_hits + 1)

    def test_warming_does_not_increment_counters(self):
        """Verify that cache warming operations don't increment the counter metrics"""
        cohort_a = self._create_cohort(name="Test Cohort A")
        self._create_cohort(
            name="Test Cohort B", groups=[{"properties": [{"key": "id", "type": "cohort", "value": cohort_a.id}]}]
        )

        cache.clear()

        initial_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="hit")._value._value
        initial_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="miss")._value._value

        warm_team_cohort_dependency_cache(self.team.id)

        # Verify counters did not increment during warming
        final_hits = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="hit")._value._value
        final_misses = COHORT_DEPENDENCY_CACHE_COUNTER.labels(cache_type="dependencies", result="miss")._value._value
        self.assertEqual(final_hits, initial_hits)
        self.assertEqual(final_misses, initial_misses)

    def test_invalid_cohort_properties_handles_validation_error(self):
        cohort = self._create_cohort(name="Test Cohort")

        initial_invalid = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependencies", result="invalid"
        )._value._value

        with mock.patch.object(type(cohort), "properties", new_callable=mock.PropertyMock) as mock_properties:
            mock_properties.side_effect = ValidationError("Invalid filters")
            result = extract_cohort_dependencies(cohort)

        self.assertEqual(result, set())
        final_invalid = COHORT_DEPENDENCY_CACHE_COUNTER.labels(
            cache_type="dependencies", result="invalid"
        )._value._value
        self.assertEqual(final_invalid, initial_invalid + 1)
