from posthog.test.base import BaseTest
from pytest import fixture
from unittest import mock

from django.core.cache import cache

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.models import Cohort
from posthog.models.cohort.cohort import CohortType
from posthog.models.cohort.dependencies import (
    COHORT_DEPENDENCY_CACHE_COUNTER,
    DEPENDENCY_CACHE_TIMEOUT,
    _extract_person_property_filters,
    _has_person_property_filters,
    _person_property_filters_changed,
    _trigger_cohort_backfill,
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


class TestCohortBackfillOnConditionsChanged(BaseTest):
    def _create_cohort(self, name: str, **kwargs):
        return Cohort.objects.create(name=name, team=self.team, **kwargs)

    @fixture(autouse=True)
    def mock_transaction(self):
        with mock.patch("django.db.transaction.on_commit", side_effect=lambda func: func()):
            yield

    def test_has_person_property_filters_with_person_properties(self):
        """Test that _has_person_property_filters correctly detects person property filters"""
        cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        self.assertTrue(_has_person_property_filters(cohort))

    def test_has_person_property_filters_without_required_fields(self):
        """Test that _has_person_property_filters returns False when required fields are missing"""
        cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    # Missing conditionHash and bytecode
                                }
                            ],
                        }
                    ],
                }
            },
        )

        self.assertFalse(_has_person_property_filters(cohort))

    def test_has_person_property_filters_with_behavioral_only(self):
        """Test that _has_person_property_filters returns False for behavioral filters only"""
        cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "pageview",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        self.assertFalse(_has_person_property_filters(cohort))

    def test_has_person_property_filters_no_filters(self):
        """Test that _has_person_property_filters returns False for cohorts without filters"""
        cohort = self._create_cohort(name="Test Cohort")
        self.assertFalse(_has_person_property_filters(cohort))

    @mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_task")
    def test_trigger_cohort_backfill_calls_celery_task(self, mock_task):
        """Test that _trigger_cohort_backfill calls the correct Celery task"""
        cohort = self._create_cohort(name="Test Cohort", cohort_type=CohortType.REALTIME)

        _trigger_cohort_backfill(cohort)

        mock_task.delay.assert_called_once_with(cohort.team_id, cohort.pk)

    @mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_task")
    def test_trigger_cohort_backfill_handles_exceptions(self, mock_task):
        """Test that _trigger_cohort_backfill handles exceptions gracefully"""
        mock_task.delay.side_effect = Exception("Task failed")
        cohort = self._create_cohort(name="Test Cohort", cohort_type=CohortType.REALTIME)

        # Should not raise an exception
        _trigger_cohort_backfill(cohort)

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch("posthoganalytics.feature_enabled", return_value=True)
    def test_backfill_signal_triggered_for_realtime_cohorts(self, mock_feature_enabled, mock_trigger_backfill):
        """Test that backfill is triggered when a realtime cohort with person properties is saved"""
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Reset mock after creation (since creation also triggers the signal)
        mock_trigger_backfill.reset_mock()

        # Update the cohort filters to trigger the signal again
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["test user"],
                                "operator": "exact",
                                "conditionHash": "xyz789",
                                "bytecode": [4, 5, 6],
                            }
                        ],
                    }
                ],
            }
        }
        cohort.save()

        mock_trigger_backfill.assert_called_once_with(cohort)

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch("posthoganalytics.feature_enabled", return_value=True)  # Flag enabled, but cohort type prevents trigger
    def test_backfill_signal_not_triggered_for_non_realtime_cohorts(self, mock_feature_enabled, mock_trigger_backfill):
        """Test that backfill is not triggered for non-realtime cohorts"""
        cohort = self._create_cohort(
            name="Test Cohort",
            # cohort_type is None (not realtime)
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Update the cohort to trigger the signal
        cohort.name = "Updated Test Cohort"
        cohort.save()

        mock_trigger_backfill.assert_not_called()

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch(
        "posthoganalytics.feature_enabled", return_value=True
    )  # Flag enabled, but static cohort prevents trigger
    def test_backfill_signal_not_triggered_for_static_cohorts(self, mock_feature_enabled, mock_trigger_backfill):
        """Test that backfill is not triggered for static cohorts"""
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            is_static=True,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Update the cohort to trigger the signal
        cohort.name = "Updated Test Cohort"
        cohort.save()

        mock_trigger_backfill.assert_not_called()

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch(
        "posthoganalytics.feature_enabled", return_value=True
    )  # Flag enabled, but no person properties prevents trigger
    def test_backfill_signal_not_triggered_without_person_properties(self, mock_feature_enabled, mock_trigger_backfill):
        """Test that backfill is not triggered for cohorts without person properties"""
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "pageview",
                                    "type": "behavioral",
                                    "value": "performed_event",
                                    "event_type": "events",
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Update the cohort to trigger the signal
        cohort.name = "Updated Test Cohort"
        cohort.save()

        mock_trigger_backfill.assert_not_called()

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch(
        "posthoganalytics.feature_enabled", return_value=True
    )  # Flag enabled, but recalculation save prevents trigger
    def test_backfill_signal_not_triggered_for_recalculation_saves(self, mock_feature_enabled, mock_trigger_backfill):
        """Test that backfill is not triggered for recalculation-only saves"""
        # Create cohort first (this will trigger the signal once)
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Reset mock after creation
        mock_trigger_backfill.reset_mock()

        # Save only recalculation fields to simulate recalculation-only update
        cohort.save(update_fields=["is_calculating", "last_calculation", "count"])

        mock_trigger_backfill.assert_not_called()

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch("posthoganalytics.feature_enabled", return_value=False)
    def test_backfill_signal_not_triggered_when_feature_flag_disabled(
        self, mock_feature_enabled, mock_trigger_backfill
    ):
        """Test that backfill is not triggered when the feature flag is disabled"""
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Reset mock after creation (since creation also triggers the signal)
        mock_trigger_backfill.reset_mock()
        mock_feature_enabled.reset_mock()

        # Update the cohort filters to trigger the signal again
        cohort.filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["test user"],
                                "operator": "exact",
                                "conditionHash": "xyz789",
                                "bytecode": [4, 5, 6],
                            }
                        ],
                    }
                ],
            }
        }
        cohort.save()

        # Verify the feature flag was checked
        mock_feature_enabled.assert_called_once_with(
            "cohort-backfill-on-change",
            str(cohort.team_id),
            groups={"team": str(cohort.team_id)},
            send_feature_flag_events=False,
        )
        # Verify backfill was not triggered due to disabled feature flag
        mock_trigger_backfill.assert_not_called()

    @mock.patch("posthog.models.cohort.dependencies._trigger_cohort_backfill")
    @mock.patch("posthoganalytics.feature_enabled", return_value=True)
    def test_backfill_signal_not_triggered_when_person_properties_unchanged(
        self, mock_feature_enabled, mock_trigger_backfill
    ):
        """Test that backfill is not triggered when person property filters haven't changed"""
        cohort = self._create_cohort(
            name="Test Cohort",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                }
                            ],
                        }
                    ],
                }
            },
        )

        # Reset mock after creation (since creation also triggers the signal)
        mock_trigger_backfill.reset_mock()
        mock_feature_enabled.reset_mock()

        # Update the cohort name but not the filters - should not trigger backfill
        cohort.name = "Updated Test Cohort"
        cohort.save()

        # Feature flag should not be checked since person properties didn't change
        mock_feature_enabled.assert_not_called()
        # Verify backfill was not triggered
        mock_trigger_backfill.assert_not_called()

    def test_extract_person_property_filters(self):
        """Test that _extract_person_property_filters correctly extracts and normalizes filters"""
        cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": ["test@example.com"],
                                    "operator": "exact",
                                    "conditionHash": "abc123",
                                    "bytecode": [1, 2, 3],
                                },
                                {
                                    "key": "age",
                                    "type": "person",
                                    "value": [25],
                                    "operator": "gt",
                                    "conditionHash": "def456",
                                    "bytecode": [4, 5, 6],
                                },
                            ],
                        }
                    ],
                }
            },
        )

        filters_hash = _extract_person_property_filters(cohort)

        # Should return a non-empty hash string for filters with person properties
        self.assertIsInstance(filters_hash, str)
        self.assertTrue(len(filters_hash) > 0)

    def test_extract_person_property_filters_empty(self):
        """Test that _extract_person_property_filters returns empty string for no filters"""
        cohort = self._create_cohort(name="Test Cohort", filters={})
        filters_hash = _extract_person_property_filters(cohort)
        self.assertEqual(filters_hash, "")

    def test_extract_person_property_filters_behavioral_only(self):
        """Test that _extract_person_property_filters ignores behavioral filters"""
        cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "key": "$pageview",
                            "type": "event",
                            "value": ["performed_event"],
                            "operator": "exact",
                        }
                    ],
                }
            },
        )

        filters_hash = _extract_person_property_filters(cohort)
        self.assertEqual(filters_hash, "")

    def test_extract_person_property_filters_order_independence(self):
        """Test that _extract_person_property_filters produces same hash regardless of child order"""
        # Create two cohorts with same conditions but different order
        cohort_order_1 = self._create_cohort(
            name="Test Cohort Order 1",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": ["test@example.com"],
                            "operator": "exact",
                            "conditionHash": "condition_1",
                            "bytecode": [1, 2, 3],
                        },
                        {
                            "key": "age",
                            "type": "person",
                            "value": [25],
                            "operator": "gte",
                            "conditionHash": "condition_2",
                            "bytecode": [4, 5, 6],
                        },
                    ],
                }
            },
        )

        cohort_order_2 = self._create_cohort(
            name="Test Cohort Order 2",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "age",
                            "type": "person",
                            "value": [25],
                            "operator": "gte",
                            "conditionHash": "condition_2",
                            "bytecode": [4, 5, 6],
                        },
                        {
                            "key": "email",
                            "type": "person",
                            "value": ["test@example.com"],
                            "operator": "exact",
                            "conditionHash": "condition_1",
                            "bytecode": [1, 2, 3],
                        },
                    ],
                }
            },
        )

        hash_1 = _extract_person_property_filters(cohort_order_1)
        hash_2 = _extract_person_property_filters(cohort_order_2)

        # Both hashes should be identical despite different child order
        self.assertEqual(hash_1, hash_2)
        # And both should be non-empty since they have person property filters
        self.assertTrue(len(hash_1) > 0)

    def test_person_property_filters_changed_new_cohort(self):
        """Test that _person_property_filters_changed returns True for new cohorts"""
        cohort = self._create_cohort(name="Test Cohort")
        cohort.pk = None  # Simulate new cohort

        result = _person_property_filters_changed(cohort)
        self.assertTrue(result)

    def test_person_property_filters_changed_filters_changed(self):
        """Test that _person_property_filters_changed detects changes"""
        # Create original cohort with one filter
        original_cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "email",
                            "type": "person",
                            "value": ["test@example.com"],
                            "operator": "exact",
                            "conditionHash": "abc123",
                            "bytecode": [1, 2, 3],
                        }
                    ],
                }
            },
        )

        # Create modified cohort with different filters
        modified_cohort = self._create_cohort(
            name="Test Cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "key": "age",
                            "type": "person",
                            "value": [25],
                            "operator": "gt",
                            "conditionHash": "def456",
                            "bytecode": [4, 5, 6],
                        }
                    ],
                }
            },
        )

        # Simulate pre_save capturing the original state hash
        original_hash = _extract_person_property_filters(original_cohort)
        modified_cohort._previous_person_property_filters = original_hash

        result = _person_property_filters_changed(modified_cohort)
        self.assertTrue(result)

    def test_person_property_filters_changed_no_change(self):
        """Test that _person_property_filters_changed returns False when filters haven't changed"""
        # Create cohorts with identical filters
        filters = {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": ["test@example.com"],
                        "operator": "exact",
                        "conditionHash": "abc123",
                        "bytecode": [1, 2, 3],
                    }
                ],
            }
        }

        cohort = self._create_cohort(name="Test Cohort", filters=filters)

        # Simulate pre_save capturing the same state hash
        current_hash = _extract_person_property_filters(cohort)
        cohort._previous_person_property_filters = current_hash

        result = _person_property_filters_changed(cohort)
        self.assertFalse(result)

    def test_person_property_filters_changed_structural_change(self):
        """Test that _person_property_filters_changed detects structural changes even with same conditions"""
        # Original: (A AND B) OR C
        original_filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "name",
                                "type": "person",
                                "value": ["Alice"],
                                "operator": "exact",
                                "conditionHash": "hashA",
                                "bytecode": [1, 2, 3],
                            },
                            {
                                "key": "age",
                                "type": "person",
                                "value": [25],
                                "operator": "gt",
                                "conditionHash": "hashB",
                                "bytecode": [4, 5, 6],
                            },
                        ],
                    },
                    {
                        "key": "email",
                        "type": "person",
                        "value": ["test@example.com"],
                        "operator": "exact",
                        "conditionHash": "hashC",
                        "bytecode": [7, 8, 9],
                    },
                ],
            }
        }

        # Modified: A OR B OR C (same conditions, different structure)
        modified_filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "key": "name",
                        "type": "person",
                        "value": ["Alice"],
                        "operator": "exact",
                        "conditionHash": "hashA",
                        "bytecode": [1, 2, 3],
                    },
                    {
                        "key": "age",
                        "type": "person",
                        "value": [25],
                        "operator": "gt",
                        "conditionHash": "hashB",
                        "bytecode": [4, 5, 6],
                    },
                    {
                        "key": "email",
                        "type": "person",
                        "value": ["test@example.com"],
                        "operator": "exact",
                        "conditionHash": "hashC",
                        "bytecode": [7, 8, 9],
                    },
                ],
            }
        }

        original_cohort = self._create_cohort(name="Test Cohort", filters=original_filters)
        modified_cohort = self._create_cohort(name="Test Cohort", filters=modified_filters)

        # Simulate pre_save capturing the original structure hash
        original_hash = _extract_person_property_filters(original_cohort)
        modified_cohort._previous_person_property_filters = original_hash

        result = _person_property_filters_changed(modified_cohort)
        self.assertTrue(result)

    def test_person_property_filters_changed_identical_structure(self):
        """Test that _person_property_filters_changed returns False for identical structure"""
        # Both: A OR B OR C (identical structure and conditions)
        filters = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "key": "name",
                        "type": "person",
                        "value": ["Alice"],
                        "operator": "exact",
                        "conditionHash": "hashA",
                        "bytecode": [1, 2, 3],
                    },
                    {
                        "key": "age",
                        "type": "person",
                        "value": [25],
                        "operator": "gt",
                        "conditionHash": "hashB",
                        "bytecode": [4, 5, 6],
                    },
                    {
                        "key": "email",
                        "type": "person",
                        "value": ["test@example.com"],
                        "operator": "exact",
                        "conditionHash": "hashC",
                        "bytecode": [7, 8, 9],
                    },
                ],
            }
        }

        cohort = self._create_cohort(name="Test Cohort", filters=filters)

        # Simulate pre_save capturing the same structure hash
        current_hash = _extract_person_property_filters(cohort)
        cohort._previous_person_property_filters = current_hash

        result = _person_property_filters_changed(cohort)
        self.assertFalse(result)
