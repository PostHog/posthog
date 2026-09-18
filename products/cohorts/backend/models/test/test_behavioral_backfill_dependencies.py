from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from django.utils.deprecation import RemovedInDjango60Warning

from parameterized import parameterized

from products.cohorts.backend.models.backfill import CohortBackfillKind
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import COHORT_REALTIME_STATE_ORPHANED_COUNTER

# (name, run kind, two successive edits as `_filters` args) — the edits move only this kind's leaf
# shape, so only this kind's receiver reacts to them even though both share one allowlist.
TRIGGER_KINDS = [
    ("behavioral", CohortBackfillKind.BEHAVIORAL, ((14, "person-a"), (30, "person-a"))),
    ("person_property", CohortBackfillKind.PERSON_PROPERTY, ((7, "person-b"), (7, "person-c"))),
]


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="all")
class TestBehavioralBackfillDependencies(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        on_commit_patch = mock.patch("django.db.transaction.on_commit", side_effect=lambda callback: callback())
        self.on_commit = on_commit_patch.start()
        self.addCleanup(on_commit_patch.stop)

    def _filters(
        self,
        window_days: int | None,
        *,
        person_hash: str | None = None,
        extra_person_hash: str | None = None,
        behavioral_hash: str | None = "stable-condition-hash",
        group_type: str = "AND",
    ) -> dict:
        values = []
        if window_days is not None:
            behavioral = {
                "type": "behavioral",
                "key": "$pageview",
                "event_type": "events",
                "value": "performed_event_multiple",
                "time_value": window_days,
                "time_interval": "day",
                "operator": "gte",
                "operator_value": 2,
            }
            # Absent rather than null, which is how the API stores a leaf whose bytecode generation
            # failed: the cohort keeps `cohort_type` realtime and the leaf keeps no condition hash.
            if behavioral_hash is not None:
                behavioral["conditionHash"] = behavioral_hash
            values.append(behavioral)
        for leaf_hash in (person_hash, extra_person_hash):
            if leaf_hash is not None:
                values.append(
                    {
                        "type": "person",
                        "key": "email",
                        "value": ["person@example.com"],
                        "operator": "exact",
                        "conditionHash": leaf_hash,
                    }
                )
        return {"properties": {"type": group_type, "values": values}}

    def _cohort(self, window_days: int | None = 7, *, person_hash: str | None = None) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(window_days, person_hash=person_hash),
        )

    def _orphan_count(self) -> float:
        return COHORT_REALTIME_STATE_ORPHANED_COUNTER.labels(reason="leaf_state_key_changed")._value._value

    def test_window_edit_writes_hash_and_nulls_readiness_in_one_save(self) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        old_person_hash = cohort.person_filters_shape_hash
        person_ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=timezone.now(),
            last_backfill_person_properties_at=person_ready_at,
        )
        cohort.refresh_from_db()
        before = self._orphan_count()

        cohort.filters = self._filters(30, person_hash="person-a")
        cohort.save()

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertNotEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertEqual(cohort.person_filters_shape_hash, old_person_hash)
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertEqual(cohort.last_backfill_person_properties_at, person_ready_at)
        self.assertEqual(self._orphan_count(), before + 1)

    def test_filter_only_update_persists_maintained_fields(self) -> None:
        cohort = self._cohort(7)
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=timezone.now(),
            last_realtime_cohort_calculation_at=timezone.now(),
        )
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertNotEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertIsNone(cohort.last_realtime_cohort_calculation_at)

    def test_positional_filter_update_persists_maintained_fields(self) -> None:
        cohort = self._cohort(7)
        old_hash = cohort.filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=timezone.now())
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        with self.assertWarns(RemovedInDjango60Warning):
            cohort.save(False, False, None, ["filters"])

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertIsNone(cohort.last_backfill_events_at)

    def test_non_filter_partial_save_does_not_maintain_shape(self) -> None:
        cohort = self._cohort(7)
        old_hash = cohort.filters_shape_hash
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=ready_at,
            last_realtime_cohort_calculation_at=ready_at,
        )
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.name = "renamed"
        cohort.save(update_fields=["name"])

        cohort.refresh_from_db()
        self.assertEqual(cohort.filters_shape_hash, old_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(cohort.last_realtime_cohort_calculation_at, ready_at)

    def test_behavioral_edit_nulls_events_readiness(self) -> None:
        cohort = self._cohort(7)
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=timezone.now(),
            last_realtime_cohort_calculation_at=timezone.now(),
        )
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertIsNone(cohort.last_realtime_cohort_calculation_at)

    def test_person_only_edit_preserves_events_readiness(self) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        ready_at = timezone.now()
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        old_person_hash = cohort.person_filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=ready_at,
            last_backfill_person_properties_at=ready_at,
            last_realtime_cohort_calculation_at=ready_at,
        )
        cohort.refresh_from_db()
        before = self._orphan_count()

        cohort.filters = self._filters(7, person_hash="person-b")
        cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertNotEqual(cohort.person_filters_shape_hash, old_person_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertIsNone(cohort.last_backfill_person_properties_at)
        # Covers the whole cohort, so a person-only edit stales it even though events
        # readiness survives.
        self.assertIsNone(cohort.last_realtime_cohort_calculation_at)
        self.assertEqual(self._orphan_count(), before)

    def test_first_legacy_save_initializes_hashes_without_invalidating_readiness(self) -> None:
        cohort = self._cohort(7)
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash=None,
            behavioral_filters_shape_hash=None,
            person_filters_shape_hash=None,
            last_backfill_events_at=ready_at,
        )
        cohort.refresh_from_db()
        before = self._orphan_count()

        cohort.name = "renamed"
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNotNone(cohort.filters_shape_hash)
        self.assertIsNotNone(cohort.behavioral_filters_shape_hash)
        self.assertIsNotNone(cohort.person_filters_shape_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(self._orphan_count(), before)

    def test_first_legacy_behavioral_edit_invalidates_readiness(self) -> None:
        cohort = self._cohort(7)
        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash=None,
            behavioral_filters_shape_hash=None,
            last_backfill_events_at=timezone.now(),
        )
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)

    @override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="999999999")
    def test_non_allowlisted_save_path_is_unchanged(self) -> None:
        ready_at = timezone.now()
        cohort = Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(7),
            last_backfill_events_at=ready_at,
            last_realtime_cohort_calculation_at=ready_at,
        )
        before = self._orphan_count()

        cohort.filters = self._filters(30)
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.filters_shape_hash)
        self.assertIsNone(cohort.behavioral_filters_shape_hash)
        self.assertIsNone(cohort.person_filters_shape_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(cohort.last_realtime_cohort_calculation_at, ready_at)
        self.assertEqual(self._orphan_count(), before)

    def _redis(self, *set_results: bool) -> mock.Mock:
        redis = mock.Mock()
        if set_results:
            redis.set.side_effect = list(set_results)
        else:
            redis.set.return_value = True
        return redis

    def test_default_trigger_allowlist_enqueues_nothing(self) -> None:
        # The trigger allowlist defaults to no teams, so merging this cannot start seeding anywhere
        # until an operator opts a team in, even though the realtime allowlist is wide open here.
        redis = self._redis()
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort = self._cohort(7, person_hash="person-a")
            cohort.filters = self._filters(30, person_hash="person-b")
            cohort.save()

        enqueue.assert_not_called()
        redis.set.assert_not_called()

    def _assert_one_debounced_task_per_kind(self, enqueue, redis, cohort: Cohort, trigger: str) -> None:
        self.assertEqual(
            {tuple(call.kwargs["args"][2:]) for call in enqueue.call_args_list},
            {(trigger, CohortBackfillKind.BEHAVIORAL), (trigger, CohortBackfillKind.PERSON_PROPERTY)},
        )
        self.assertEqual({call.kwargs["countdown"] for call in enqueue.call_args_list}, {300})
        self.assertEqual(
            {call.args[0] for call in redis.set.call_args_list},
            {
                f"cohort_backfill_behavioral_pending:{cohort.id}",
                f"cohort_backfill_person_property_pending:{cohort.id}",
            },
        )
        # Without nx every save enqueues a replay; without ex outliving the countdown, an expired
        # window swallows saves forever. Both are the debounce design's whole contract.
        for call in redis.set.call_args_list:
            self.assertEqual(call.kwargs, {"nx": True, "ex": 300})

    @override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all")
    def test_create_enqueues_one_debounced_task_per_leaf_kind(self) -> None:
        # A new cohort has no stored hash to differ from, so its shape-changed flag is False here.
        # Guarding the receivers on that flag alone would silently never seed a newly created cohort.
        redis = self._redis()
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort = self._cohort(7, person_hash="person-a")

        self._assert_one_debounced_task_per_kind(enqueue, redis, cohort, "cohort_created")

    def test_edit_touching_both_leaf_kinds_enqueues_one_task_per_kind(self) -> None:
        # The kinds seed different stores, so one save that moves both shapes owes a task to each, on
        # keys that cannot debounce one another. The cohort is created before the trigger allowlist
        # opens, so the create dispatches nothing real behind the edit's mocks.
        cohort = self._cohort(7, person_hash="person-a")
        redis = self._redis()
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort.filters = self._filters(30, person_hash="person-b")
            cohort.save()

        self._assert_one_debounced_task_per_kind(enqueue, redis, cohort, "cohort_edited")

    def _assert_one_debounced_task(self, enqueue, redis, cohort: Cohort, kind: CohortBackfillKind) -> None:
        enqueue.assert_called_once_with(
            args=[self.team.id, cohort.id, "cohort_edited", kind],
            countdown=300,
        )
        # The value is the pending task's trigger kind, which the cohort API reads to show a build
        # as queued during the countdown, before any run row exists.
        redis.set.assert_called_once_with(
            f"cohort_backfill_{kind.value}_pending:{cohort.id}", "cohort_edited", nx=True, ex=300
        )

    @parameterized.expand(
        [
            (
                "group_operator_on_mixed",
                {"window_days": 7, "person_hash": "person-a"},
                {"window_days": 7, "person_hash": "person-a", "group_type": "OR"},
                CohortBackfillKind.BEHAVIORAL,
            ),
            (
                "group_operator_on_person_only",
                {"window_days": None, "person_hash": "person-a", "extra_person_hash": "person-b"},
                {
                    "window_days": None,
                    "person_hash": "person-a",
                    "extra_person_hash": "person-b",
                    "group_type": "OR",
                },
                CohortBackfillKind.PERSON_PROPERTY,
            ),
            (
                "last_person_leaf_removed",
                {"window_days": 7, "person_hash": "person-a"},
                {"window_days": 7},
                CohortBackfillKind.BEHAVIORAL,
            ),
            (
                "last_behavioral_leaf_removed",
                {"window_days": 7, "person_hash": "person-a"},
                {"window_days": None, "person_hash": "person-a"},
                CohortBackfillKind.PERSON_PROPERTY,
            ),
        ]
    )
    def test_edit_no_leaf_set_run_repairs_enqueues_one_runnable_kind(
        self, _name: str, before: dict, after: dict, kind: CohortBackfillKind
    ) -> None:
        # Reconcile evaluates the whole tree whichever kind it runs for, so one run repairs the
        # cohort. Removing the last person leaf is in this set because the person run its hash change
        # would ask for is refused: the cohort has no person leaf left to pin.
        cohort = Cohort.objects.create(team=self.team, cohort_type=CohortType.REALTIME, filters=self._filters(**before))
        redis = self._redis()
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort.filters = self._filters(**after)
            cohort.save()

        self._assert_one_debounced_task(enqueue, redis, cohort, kind)

    @parameterized.expand([("group_operator", None), ("empty_and", "AND"), ("empty_or", "OR")])
    def test_composition_edit_nulls_the_events_stamp_and_moves_no_kind_hash(
        self, _name: str, empty_group: str | None
    ) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        old_person_hash = cohort.person_filters_shape_hash
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            last_backfill_events_at=ready_at,
            last_backfill_person_properties_at=ready_at,
            last_realtime_cohort_calculation_at=ready_at,
        )
        cohort.refresh_from_db()
        before = self._orphan_count()

        # A partial save, because `resave_cohorts` re-drives the fleet with a frozen field set. The
        # stamp this edit nulls has to be added to that set, or the null is decided and never written.
        if empty_group is None:
            cohort.filters = self._filters(7, person_hash="person-a", group_type="OR")
        else:
            assert cohort.filters is not None
            cohort.filters["properties"]["values"].append({"type": empty_group, "values": []})
        cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        # Runs in flight pin these columns and the processor, the seeder and the finalizer compare
        # them, so the replacement run must pin what the superseded one did.
        self.assertEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertEqual(cohort.person_filters_shape_hash, old_person_hash)
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertEqual(cohort.last_backfill_person_properties_at, ready_at)
        self.assertIsNone(cohort.last_realtime_cohort_calculation_at)
        self.assertEqual(self._orphan_count(), before + 1)

    def test_adding_the_first_person_leaf_enqueues_only_the_person_run(self) -> None:
        # The person run already reconciles the whole cohort, so the composition rule must not add a
        # behavioral history replay to an edit that triggers a run on its own.
        cohort = self._cohort(7)
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=ready_at)
        cohort.refresh_from_db()
        redis = self._redis()
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort.filters = self._filters(7, person_hash="person-a")
            cohort.save()

        self._assert_one_debounced_task(enqueue, redis, cohort, CohortBackfillKind.PERSON_PROPERTY)
        cohort.refresh_from_db()
        self.assertEqual(cohort.last_backfill_events_at, ready_at)

    def test_behavioral_leaf_losing_its_hash_enqueues_only_the_behavioral_run(self) -> None:
        # The behavioral receiver creates a run for any behavioral leaf, hashed or not, so this edit
        # already triggers one and the composition rule must not add a person run beside it. The API
        # reaches this state by storing the raw filters when filter validation raises, which leaves
        # the cohort realtime with a leaf that never got a condition hash.
        cohort = self._cohort(7, person_hash="person-a")
        redis = self._redis()
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort.filters = self._filters(7, person_hash="person-a", behavioral_hash=None)
            cohort.save()

        self._assert_one_debounced_task(enqueue, redis, cohort, CohortBackfillKind.BEHAVIORAL)

    @parameterized.expand([("stored_hashes", False), ("null_hashes", True)])
    def test_malformed_persisted_filters_still_invalidate_on_a_leaf_edit(self, _name: str, null_hashes: bool) -> None:
        # The composition signal reads the persisted filters, which the leaf-shape comparison never
        # had to parse. A row the renderer cannot walk must cost only that signal: the method
        # swallows its own exceptions, so letting one escape here would silently turn off every
        # invalidation for this cohort, including the leaf edits that worked before the rule existed.
        cohort = self._cohort(7, person_hash="person-a")
        Cohort.objects.filter(id=cohort.id).update(
            filters={"properties": {"type": "AND", "values": 3}},
            behavioral_filters_shape_hash=None if null_hashes else cohort.behavioral_filters_shape_hash,
            person_filters_shape_hash=None if null_hashes else cohort.person_filters_shape_hash,
            last_backfill_events_at=timezone.now(),
            last_backfill_person_properties_at=timezone.now(),
        )
        cohort.refresh_from_db()

        cohort.filters = self._filters(30, person_hash="person-b")
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertIsNone(cohort.last_backfill_person_properties_at)
        self.assertTrue(cohort.behavioral_filters_shape_hash)
        self.assertTrue(cohort.person_filters_shape_hash)

    @parameterized.expand([("legacy_hash", True), ("current_hash", False)])
    def test_save_with_unchanged_filters_enqueues_nothing(self, _name: str, legacy_hash: bool) -> None:
        # Every stored full hash was computed from the leaf set alone before the fingerprint existed.
        # Reading the previous definition from that column rather than from the persisted filters
        # would turn each cohort's first save after the deploy into an edit, and the fleet would
        # replay its history for nothing.
        cohort = self._cohort(7, person_hash="person-a")
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        old_person_hash = cohort.person_filters_shape_hash
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash="a-hash-written-under-the-old-rule" if legacy_hash else cohort.filters_shape_hash,
            last_backfill_events_at=ready_at,
            last_backfill_person_properties_at=ready_at,
            last_realtime_cohort_calculation_at=ready_at,
        )
        cohort.refresh_from_db()
        redis = self._redis()
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            cohort.name = "renamed"
            cohort.save()

        enqueue.assert_not_called()
        redis.set.assert_not_called()
        cohort.refresh_from_db()
        self.assertEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertEqual(cohort.person_filters_shape_hash, old_person_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(cohort.last_backfill_person_properties_at, ready_at)
        self.assertEqual(cohort.last_realtime_cohort_calculation_at, ready_at)

    def test_stale_instance_restoring_definition_invalidates_readiness(self) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        stale = Cohort.objects.get(id=cohort.id)
        cohort.filters = self._filters(7, person_hash="person-a", group_type="OR")
        cohort.save(update_fields=["filters"])
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=timezone.now())

        stale.name = "renamed"
        stale.save()

        stale.refresh_from_db()
        assert stale.filters is not None
        self.assertEqual(stale.filters["properties"]["type"], "AND")
        self.assertIsNone(stale.last_backfill_events_at)

    @parameterized.expand(TRIGGER_KINDS)
    def test_two_edits_share_one_debounce_key(self, _name: str, kind: CohortBackfillKind, edits) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        redis = self._redis(True, False)
        with (
            override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all"),
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            for window_days, person_hash in edits:
                cohort.filters = self._filters(window_days, person_hash=person_hash)
                cohort.save()

        enqueue.assert_called_once_with(
            args=[self.team.id, cohort.id, "cohort_edited", kind],
            countdown=300,
        )
        # The value is the pending task's trigger kind, which the cohort API reads to show a build
        # as queued during the countdown, before any run row exists.
        self.assertEqual(
            redis.set.call_args_list,
            [mock.call(f"cohort_backfill_{kind.value}_pending:{cohort.id}", "cohort_edited", nx=True, ex=300)] * 2,
        )

    @parameterized.expand(
        [
            ("static", {"is_static": True}),
            ("non_realtime_type", {"cohort_type": None}),
        ]
    )
    @override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all")
    def test_ineligible_create_enqueues_nothing(self, _name: str, overrides: dict) -> None:
        # Creates skip the shape-changed flags and dispatch straight off kwargs["created"], so the
        # type guard in _backfill_trigger_kind is all that keeps every ordinary (static or
        # non-realtime) cohort create in an opted-in team from firing tasks the creators refuse.
        redis = self._redis()
        params: dict = {
            "team": self.team,
            "cohort_type": CohortType.REALTIME,
            "filters": self._filters(7, person_hash="person-a"),
            **overrides,
        }
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            Cohort.objects.create(**params)

        enqueue.assert_not_called()
        redis.set.assert_not_called()

    @override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="999999999", COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all")
    def test_trigger_allowlisted_but_non_realtime_team_enqueues_nothing(self) -> None:
        # The trigger allowlist opts a team in on top of realtime membership. Without the receivers'
        # realtime gate, this misconfiguration would debounce a task on every create that the
        # creators are guaranteed to refuse, forever, with nothing pointing at the cause.
        redis = self._redis()
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async") as enqueue,
        ):
            self._cohort(7, person_hash="person-a")

        enqueue.assert_not_called()
        redis.set.assert_not_called()

    @override_settings(COHORT_BACKFILL_TRIGGER_TEAM_ALLOWLIST="all")
    def test_failed_enqueue_releases_the_debounce_lock(self) -> None:
        # If the broker rejects the publish after the lock is claimed, the lock has to be released,
        # or every save in the next window is swallowed with no task behind the key.
        redis = self._redis()
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch(
                "posthog.tasks.calculate_cohort.trigger_cohort_backfill_run_task.apply_async",
                side_effect=Exception("broker down"),
            ),
        ):
            cohort = self._cohort(7)

        redis.delete.assert_called_once_with(f"cohort_backfill_behavioral_pending:{cohort.id}")

    def test_hashing_failure_in_maintain_shape_does_not_break_save(self) -> None:
        # _maintain_filter_shape_hashes swallows hashing errors so a hashing bug can't take down every
        # realtime cohort save. This exercises that guard directly by making the hash raise.
        cohort = self._cohort(7)
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=ready_at)
        cohort.refresh_from_db()

        with mock.patch(
            "products.cohorts.backend.models.cohort.extract_leaf_shape_hash",
            side_effect=RuntimeError("hash boom"),
        ):
            cohort.name = "renamed"
            cohort.filters = self._filters(30)
            cohort.save()

        cohort.refresh_from_db()
        self.assertEqual(cohort.name, "renamed")
        # The guard bailed before the readiness-null branch, so events readiness is left intact.
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
