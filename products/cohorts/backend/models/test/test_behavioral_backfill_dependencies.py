from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings
from django.utils import timezone
from django.utils.deprecation import RemovedInDjango60Warning

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import COHORT_REALTIME_STATE_ORPHANED_COUNTER


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="all")
class TestBehavioralBackfillDependencies(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        on_commit_patch = mock.patch("django.db.transaction.on_commit", side_effect=lambda callback: callback())
        self.on_commit = on_commit_patch.start()
        self.addCleanup(on_commit_patch.stop)

        feature_patch = mock.patch(
            "products.cohorts.backend.models.dependencies.posthoganalytics.feature_enabled", return_value=False
        )
        self.feature_enabled = feature_patch.start()
        self.addCleanup(feature_patch.stop)

    def _filters(self, window_days: int, *, person_hash: str | None = None) -> dict:
        values = [
            {
                "type": "behavioral",
                "key": "$pageview",
                "event_type": "events",
                "value": "performed_event_multiple",
                "conditionHash": "stable-condition-hash",
                "time_value": window_days,
                "time_interval": "day",
                "operator": "gte",
                "operator_value": 2,
            }
        ]
        if person_hash is not None:
            values.append(
                {
                    "type": "person",
                    "key": "email",
                    "value": ["person@example.com"],
                    "operator": "exact",
                    "conditionHash": person_hash,
                }
            )
        return {"properties": {"type": "AND", "values": values}}

    def _cohort(self, window_days: int = 7, *, person_hash: str | None = None) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._filters(window_days, person_hash=person_hash),
        )

    def _orphan_count(self) -> float:
        return COHORT_REALTIME_STATE_ORPHANED_COUNTER.labels(reason="leaf_state_key_changed")._value._value

    def test_window_edit_writes_hash_and_nulls_readiness_in_one_save(self) -> None:
        cohort = self._cohort(7)
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=timezone.now())
        cohort.refresh_from_db()
        before = self._orphan_count()

        cohort.filters = self._filters(30)
        cohort.save()

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertNotEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertEqual(self._orphan_count(), before + 1)

    def test_filter_only_update_persists_maintained_fields(self) -> None:
        cohort = self._cohort(7)
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=timezone.now())
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.save(update_fields=["filters"])

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertNotEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertIsNone(cohort.last_backfill_events_at)

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
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=ready_at)
        cohort.refresh_from_db()

        cohort.filters = self._filters(30)
        cohort.name = "renamed"
        cohort.save(update_fields=["name"])

        cohort.refresh_from_db()
        self.assertEqual(cohort.filters_shape_hash, old_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)

    def test_flag_off_still_nulls_readiness_without_enqueue(self) -> None:
        cohort = self._cohort(7)
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=timezone.now())
        cohort.refresh_from_db()
        with mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async") as enqueue:
            cohort.filters = self._filters(30)
            cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)
        enqueue.assert_not_called()

    def test_person_only_edit_preserves_events_readiness(self) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        ready_at = timezone.now()
        old_hash = cohort.filters_shape_hash
        old_behavioral_hash = cohort.behavioral_filters_shape_hash
        Cohort.objects.filter(id=cohort.id).update(last_backfill_events_at=ready_at)
        cohort.refresh_from_db()
        before = self._orphan_count()
        self.feature_enabled.return_value = True
        redis = mock.Mock()
        redis.set.return_value = True

        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_task.apply_async") as person_enqueue,
            mock.patch(
                "posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async"
            ) as event_enqueue,
        ):
            cohort.filters = self._filters(7, person_hash="person-b")
            cohort.save()

        cohort.refresh_from_db()
        self.assertNotEqual(cohort.filters_shape_hash, old_hash)
        self.assertEqual(cohort.behavioral_filters_shape_hash, old_behavioral_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(self._orphan_count(), before)
        person_enqueue.assert_called_once()
        event_enqueue.assert_not_called()

    def test_first_legacy_save_initializes_hashes_without_invalidating_readiness(self) -> None:
        cohort = self._cohort(7)
        ready_at = timezone.now()
        Cohort.objects.filter(id=cohort.id).update(
            filters_shape_hash=None,
            behavioral_filters_shape_hash=None,
            last_backfill_events_at=ready_at,
        )
        cohort.refresh_from_db()
        before = self._orphan_count()
        self.feature_enabled.return_value = True

        with mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async") as enqueue:
            cohort.name = "renamed"
            cohort.save()

        cohort.refresh_from_db()
        self.assertIsNotNone(cohort.filters_shape_hash)
        self.assertIsNotNone(cohort.behavioral_filters_shape_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(self._orphan_count(), before)
        enqueue.assert_not_called()

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
        )
        before = self._orphan_count()

        cohort.filters = self._filters(30)
        cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.filters_shape_hash)
        self.assertIsNone(cohort.behavioral_filters_shape_hash)
        self.assertEqual(cohort.last_backfill_events_at, ready_at)
        self.assertEqual(self._orphan_count(), before)

    def test_two_edits_share_the_events_debounce_key(self) -> None:
        cohort = self._cohort(7)
        self.feature_enabled.return_value = True
        redis = mock.Mock()
        redis.set.side_effect = [True, False]
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async") as enqueue,
        ):
            cohort.filters = self._filters(14)
            cohort.save()
            cohort.filters = self._filters(30)
            cohort.save()

        enqueue.assert_called_once_with(
            args=[self.team.id, cohort.id, "cohort_edited"],
            countdown=300,
        )

    def test_person_and_behavioral_changes_enqueue_separate_tasks(self) -> None:
        cohort = self._cohort(7, person_hash="person-a")
        self.feature_enabled.return_value = True
        redis = mock.Mock()
        redis.set.return_value = True
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_backfill_task.apply_async") as person_enqueue,
            mock.patch(
                "posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async"
            ) as event_enqueue,
        ):
            cohort.filters = self._filters(30, person_hash="person-b")
            cohort.save()

        person_enqueue.assert_called_once()
        event_enqueue.assert_called_once()
        self.assertEqual(
            {call.args[0] for call in redis.set.call_args_list},
            {f"cohort_backfill_pending:{cohort.id}", f"cohort_backfill_events_pending:{cohort.id}"},
        )

    def test_create_path_enqueues_behavioral_backfill(self) -> None:
        self.feature_enabled.return_value = True
        redis = mock.Mock()
        redis.set.return_value = True
        with (
            mock.patch("products.cohorts.backend.models.dependencies.get_redis_client", return_value=redis),
            mock.patch("posthog.tasks.calculate_cohort.trigger_cohort_events_backfill_task.apply_async") as enqueue,
        ):
            cohort = self._cohort(7)

        enqueue.assert_called_once_with(
            args=[self.team.id, cohort.id, "cohort_created"],
            countdown=300,
        )

    def test_receiver_failure_does_not_break_save(self) -> None:
        cohort = self._cohort(7)

        with mock.patch(
            "products.cohorts.backend.models.dependencies._has_behavioral_filters",
            side_effect=RuntimeError("broken detector"),
        ):
            cohort.filters = self._filters(30)
            cohort.save()

        cohort.refresh_from_db()
        self.assertIsNone(cohort.last_backfill_events_at)

    def test_hashing_failure_in_maintain_shape_does_not_break_save(self) -> None:
        # _maintain_behavioral_shape swallows hashing errors so a hashing bug can't take down every
        # realtime cohort save. The receiver-guard test above patches a different try/except in the
        # signal path; this one exercises the save-path guard directly by making the hash raise.
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
