import importlib

from posthog.test.base import BaseTest
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.tasks.calculate_cohort import finalize_cohort_backfill_runs

from products.cohorts.backend.backfill.finalize import FLAGS_CACHE_TASK, finalize_backfill_runs
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.dependencies import _behavioral_cohort_ids_key


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_FINALIZER_ENABLED=True,
)
class TestBackfillFinalizer(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        feature_patch = mock.patch(
            "products.cohorts.backend.models.dependencies.posthoganalytics.feature_enabled", return_value=False
        )
        feature_patch.start()
        self.addCleanup(feature_patch.stop)

        celery_patch = mock.patch("products.cohorts.backend.backfill.finalize.current_app")
        self.mock_celery_app = celery_patch.start()
        self.addCleanup(celery_patch.stop)

    def _behavioral_filters(self) -> dict:
        return {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "behavioral",
                        "key": "$pageview",
                        "event_type": "events",
                        "value": "performed_event_multiple",
                        "conditionHash": "same-condition-hash",
                        "time_value": 7,
                        "time_interval": "day",
                        "operator": "gte",
                        "operator_value": 2,
                    }
                ],
            }
        }

    def _make_participation(self, run: CohortBackfillRun, outcome: str) -> tuple[Cohort, CohortBackfillRunCohort]:
        cohort = Cohort.objects.create(
            team=self.team,
            cohort_type=CohortType.REALTIME,
            filters=self._behavioral_filters(),
        )
        ensure_filters_shape_hash(cohort)
        cohort.refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).create(
            run=run,
            team_id=self.team.id,
            cohort=cohort,
            filters_shape_hash=cohort.filters_shape_hash or "",
            behavioral_filters_shape_hash=cohort.behavioral_filters_shape_hash or "",
            pinned_filters=cohort.filters,
        )
        # Simulate the Rust seeder's per-participation outcome writes (the columns are the interface).
        now = timezone.now()
        rows = CohortBackfillRunCohort.objects.for_team(self.team.id).filter(id=participation.id)
        if outcome == "completed":
            rows.update(reconcile_completed_at=now)
        elif outcome == "superseded":
            rows.update(superseded_at=now, error="missing partitions [3, 9]")
        elif outcome == "superseded_and_completed":
            rows.update(superseded_at=now, reconcile_completed_at=now, error="missing partitions [3, 9]")
        elif outcome == "completed_then_diverged":
            # Reconcile completed, then the cohort's behavioral definition changed: the stamp CAS
            # must refuse and supersede instead of opening readiness on a stale backfill.
            rows.update(reconcile_completed_at=now)
            Cohort.objects.filter(id=cohort.id).update(behavioral_filters_shape_hash="diverged-after-reconcile")
        elif outcome == "shortfall":
            rows.update(error="markers short, retryable")
        elif outcome == "missing_outcome":
            pass  # nothing written despite reconcile_observed_at
        else:
            raise ValueError(outcome)
        return cohort, participation

    def _make_run(
        self, outcomes: list[str], *, observed: bool = True, scope: str = CohortBackfillScope.TEAM
    ) -> tuple[CohortBackfillRun, list[Cohort]]:
        cohort_scoped = scope == CohortBackfillScope.COHORT
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=(
                CohortBackfillTrigger.COHORT_CREATED if cohort_scoped else CohortBackfillTrigger.TEAM_ENABLEMENT
            ),
            scope=scope,
            status=CohortBackfillRunStatus.RECONCILING,
            reconcile_observed_at=timezone.now() if observed else None,
            timezone="UTC",
        )
        cohorts = [self._make_participation(run, outcome)[0] for outcome in outcomes]
        if cohort_scoped:
            run.cohort = cohorts[0]
            run.save(update_fields=["cohort"])
        return run, cohorts

    @parameterized.expand(
        [
            ("all_completed", ["completed", "completed"], CohortBackfillRunStatus.COMPLETED, [0, 1]),
            ("completed_and_superseded", ["completed", "superseded"], CohortBackfillRunStatus.COMPLETED, [0]),
            ("all_superseded", ["superseded", "superseded"], CohortBackfillRunStatus.SUPERSEDED, []),
            ("superseded_trumps_completed", ["superseded_and_completed"], CohortBackfillRunStatus.SUPERSEDED, []),
            ("shortfall_holds", ["shortfall"], CohortBackfillRunStatus.RECONCILING, []),
            # No outcome at all despite reconcile_observed_at must hold the run rather than
            # terminalize it on incomplete information.
            ("missing_outcome_holds", ["missing_outcome"], CohortBackfillRunStatus.RECONCILING, []),
            ("mixed_held_still_stamps", ["completed", "shortfall"], CohortBackfillRunStatus.RECONCILING, [0]),
        ]
    )
    def test_outcome_matrix(
        self, _name: str, outcomes: list[str], expected_status: str, stamped_indices: list[int]
    ) -> None:
        run, cohorts = self._make_run(outcomes)

        finalize_backfill_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, expected_status)
        for index, cohort in enumerate(cohorts):
            cohort.refresh_from_db()
            participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run, cohort=cohort)
            if index in stamped_indices:
                self.assertIsNotNone(cohort.last_backfill_events_at)
                self.assertIsNotNone(participation.stamped_at)
            else:
                self.assertIsNone(cohort.last_backfill_events_at)
                self.assertIsNone(participation.stamped_at)

    def test_unobserved_run_is_untouched(self) -> None:
        run, cohorts = self._make_run(["completed"], observed=False)

        result = finalize_backfill_runs()

        run.refresh_from_db()
        cohorts[0].refresh_from_db()
        self.assertEqual(result.runs_scanned, 0)
        self.assertEqual(run.status, CohortBackfillRunStatus.RECONCILING)
        self.assertIsNone(cohorts[0].last_backfill_events_at)

    def test_observed_person_run_is_untouched(self) -> None:
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            backfill_kind=CohortBackfillKind.PERSON_PROPERTY,
            trigger_kind=CohortBackfillTrigger.TEAM_ENABLEMENT,
            scope=CohortBackfillScope.TEAM,
            status=CohortBackfillRunStatus.RECONCILING,
            reconcile_observed_at=timezone.now(),
            timezone="UTC",
        )
        cohort, participation = self._make_participation(run, "completed")

        result = finalize_backfill_runs()

        run.refresh_from_db()
        cohort.refresh_from_db()
        participation.refresh_from_db()
        self.assertEqual(result.runs_scanned, 0)
        self.assertEqual(run.status, CohortBackfillRunStatus.RECONCILING)
        self.assertIsNone(cohort.last_backfill_events_at)
        self.assertIsNone(cohort.last_backfill_person_properties_at)
        self.assertIsNone(participation.stamped_at)

    def test_second_fire_is_a_noop(self) -> None:
        run, _cohorts = self._make_run(["completed", "completed"])

        first = finalize_backfill_runs()
        second = finalize_backfill_runs()

        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(first.completed, 1)
        self.assertEqual(second.runs_scanned, 0)
        self.assertEqual(second.completed, 0)
        self.assertEqual(self.mock_celery_app.send_task.call_count, 1)

    @override_settings(BEHAVIORAL_BACKFILL_FINALIZER_ENABLED=False)
    def test_disabled_setting_does_not_touch_the_db(self) -> None:
        run, cohorts = self._make_run(["completed"])

        with CaptureQueriesContext(connection) as queries:
            finalize_cohort_backfill_runs()

        self.assertEqual(len(queries), 0)
        run.refresh_from_db()
        cohorts[0].refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.RECONCILING)
        self.assertIsNone(cohorts[0].last_backfill_events_at)

    def test_stamping_pass_invalidates_team_caches(self) -> None:
        cache.set(_behavioral_cohort_ids_key(self.team.id, True), [1, 2, 3], 300)
        cache.set(_behavioral_cohort_ids_key(self.team.id, False), [1, 2, 3], 300)
        self._make_run(["completed"])

        finalize_backfill_runs()

        self.assertIsNone(cache.get(_behavioral_cohort_ids_key(self.team.id, True)))
        self.assertIsNone(cache.get(_behavioral_cohort_ids_key(self.team.id, False)))
        self.mock_celery_app.send_task.assert_called_once_with(
            FLAGS_CACHE_TASK, args=(self.team.id,), queue="feature_flags"
        )

    def test_flags_cache_task_name_matches_the_registered_task(self) -> None:
        # The dispatch is by name (a static import would create a product-dependency cycle), so pin
        # the string against the task's registered name to catch a rename or move.
        module_path, task_name = FLAGS_CACHE_TASK.rsplit(".", 1)
        task = getattr(importlib.import_module(module_path), task_name)
        self.assertEqual(task.name, FLAGS_CACHE_TASK)

    def test_cohort_scoped_run_superseded_by_stamp_divergence(self) -> None:
        # The cohort's definition diverged after reconcile completed: the stamp CAS must refuse,
        # supersede the participation and (cohort scope) the run itself, and the finalizer must
        # count the run superseded despite its own terminal CAS missing.
        run, cohorts = self._make_run(["completed_then_diverged"], scope=CohortBackfillScope.COHORT)

        result = finalize_backfill_runs()

        run.refresh_from_db()
        cohorts[0].refresh_from_db()
        participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run=run)
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(participation.superseded_at)
        self.assertIsNone(participation.stamped_at)
        self.assertIsNone(cohorts[0].last_backfill_events_at)
        self.assertEqual(result.superseded, 1)
        self.assertEqual(result.completed, 0)
        self.mock_celery_app.send_task.assert_not_called()

    def test_cohort_scoped_run_with_a_second_participation_keeps_the_stamp(self) -> None:
        # Only creation-time code gives a cohort-scoped run exactly one participation, and the
        # terminal CAS reads that invariant. With two, the diverged one supersedes the run row
        # mid-transaction so the CAS misses — the stamp that already landed must survive with its
        # cache invalidation, and the violation must be logged rather than silently miscounted.
        with mock.patch("products.cohorts.backend.backfill.finalize.logger") as mock_logger:
            run, cohorts = self._make_run(["completed", "completed_then_diverged"], scope=CohortBackfillScope.COHORT)

            result = finalize_backfill_runs()

        run.refresh_from_db()
        cohorts[0].refresh_from_db()
        cohorts[1].refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.SUPERSEDED)
        self.assertIsNotNone(cohorts[0].last_backfill_events_at)
        self.assertIsNone(cohorts[1].last_backfill_events_at)
        self.assertEqual(result.superseded, 1)
        self.assertEqual(result.stamped_participations, 1)
        self.mock_celery_app.send_task.assert_called_once_with(
            FLAGS_CACHE_TASK, args=(self.team.id,), queue="feature_flags"
        )
        self.assertEqual(
            mock_logger.error.call_args[0][0], "cohort_backfill_finalizer_cohort_scoped_run_participation_count"
        )
