import importlib
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.tasks.calculate_cohort import finalize_cohort_backfill_runs

from products.cohorts.backend.backfill.finalize import _STAMP_BY_KIND, FLAGS_CACHE_TASK, finalize_backfill_runs
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


class TestFinalizerKindCoverage(SimpleTestCase):
    def test_every_backfill_kind_has_a_stamp(self) -> None:
        unmapped = set(CohortBackfillKind.values) - set(_STAMP_BY_KIND)
        assert not unmapped, (
            f"{sorted(unmapped)} has no entry in finalize._STAMP_BY_KIND, so the finalizer's "
            "discovery filters those runs out entirely: they park in reconciling forever with no "
            "exception, no error count, and no gauge movement"
        )


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_FINALIZER_ENABLED=True,
    BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=True,
)
class TestBackfillFinalizer(BaseTest):
    def setUp(self) -> None:
        super().setUp()

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
                    },
                    {
                        "type": "person",
                        "key": "email",
                        "value": ["person@example.com"],
                        "operator": "exact",
                        "conditionHash": "person-condition-hash",
                    },
                ],
            }
        }

    def _make_participation(
        self, run: CohortBackfillRun, outcome: str, cohort: Cohort | None = None
    ) -> tuple[Cohort, CohortBackfillRunCohort]:
        if cohort is None:
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
            person_filters_shape_hash=cohort.person_filters_shape_hash or "",
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
        self,
        outcomes: list[str],
        *,
        observed: bool = True,
        scope: str = CohortBackfillScope.TEAM,
        kind: str = CohortBackfillKind.BEHAVIORAL,
        cohorts: list[Cohort] | None = None,
    ) -> tuple[CohortBackfillRun, list[Cohort]]:
        cohort_scoped = scope == CohortBackfillScope.COHORT
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            backfill_kind=kind,
            trigger_kind=(
                CohortBackfillTrigger.COHORT_CREATED if cohort_scoped else CohortBackfillTrigger.TEAM_ENABLEMENT
            ),
            scope=scope,
            status=CohortBackfillRunStatus.RECONCILING,
            reconcile_observed_at=timezone.now() if observed else None,
            timezone="UTC",
        )
        shared = cohorts if cohorts is not None else [None] * len(outcomes)
        cohorts = [
            self._make_participation(run, outcome, cohort=cohort)[0]
            for outcome, cohort in zip(outcomes, shared, strict=True)
        ]
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

    def test_one_pass_finalizes_each_kind_into_its_own_column(self) -> None:
        behavioral, behavioral_cohorts = self._make_run(["completed"])
        person, person_cohorts = self._make_run(["completed"], kind=CohortBackfillKind.PERSON_PROPERTY)

        result = finalize_backfill_runs()

        behavioral.refresh_from_db()
        person.refresh_from_db()
        behavioral_cohorts[0].refresh_from_db()
        person_cohorts[0].refresh_from_db()
        self.assertEqual(result.completed, 2)
        self.assertEqual(behavioral.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(person.status, CohortBackfillRunStatus.COMPLETED)
        # Each run stamps its own column and leaves the other for its sibling to earn. Both cohorts
        # are mixed, so neither is flag-compatible off one run.
        self.assertIsNotNone(behavioral_cohorts[0].last_backfill_events_at)
        self.assertIsNone(behavioral_cohorts[0].last_backfill_person_properties_at)
        self.assertIsNotNone(person_cohorts[0].last_backfill_person_properties_at)
        self.assertIsNone(person_cohorts[0].last_backfill_events_at)
        self.assertFalse(behavioral_cohorts[0].is_flag_compatible)
        self.assertFalse(person_cohorts[0].is_flag_compatible)

    def test_mixed_cohort_earns_both_stamps_from_two_runs_on_one_cohort(self) -> None:
        # The production shape `cohort_bfr_active_team_kind_uq` permits: one mixed cohort reached by
        # two team-scoped runs, one per kind. The second stamp must neither be blocked by nor clobber
        # the first — only with both columns does the cohort become flag-compatible.
        behavioral, cohorts = self._make_run(["completed"])
        person, _ = self._make_run(["completed"], kind=CohortBackfillKind.PERSON_PROPERTY, cohorts=cohorts)

        result = finalize_backfill_runs()

        behavioral.refresh_from_db()
        person.refresh_from_db()
        cohorts[0].refresh_from_db()
        self.assertEqual(result.completed, 2)
        self.assertEqual(behavioral.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(person.status, CohortBackfillRunStatus.COMPLETED)
        self.assertIsNotNone(cohorts[0].last_backfill_events_at)
        self.assertIsNotNone(cohorts[0].last_backfill_person_properties_at)
        self.assertTrue(cohorts[0].is_flag_compatible)

    @override_settings(BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=False)
    def test_person_run_is_held_not_superseded_while_the_readiness_gate_is_off(self) -> None:
        behavioral, behavioral_cohorts = self._make_run(["completed"])
        person, person_cohorts = self._make_run(["completed"], kind=CohortBackfillKind.PERSON_PROPERTY)

        result = finalize_backfill_runs()

        behavioral.refresh_from_db()
        person.refresh_from_db()
        behavioral_cohorts[0].refresh_from_db()
        person_cohorts[0].refresh_from_db()
        person_participation = CohortBackfillRunCohort.objects.for_team(self.team.id).get(run_id=person.id)
        # The behavioral run is unaffected: the gate narrows discovery by kind, not the whole pass.
        self.assertEqual(behavioral.status, CohortBackfillRunStatus.COMPLETED)
        self.assertIsNotNone(behavioral_cohorts[0].last_backfill_events_at)
        # No stamp: the flags service reads this column as proof cohort_membership is populated.
        self.assertIsNone(person_cohorts[0].last_backfill_person_properties_at)
        # Held, not discarded. Gating inside the stamp would supersede the participation, throwing
        # away a completed person backfill that should finalize once the gate opens.
        self.assertEqual(person.status, CohortBackfillRunStatus.RECONCILING)
        self.assertIsNone(person_participation.superseded_at)
        self.assertIsNone(person_participation.stamped_at)
        self.assertEqual(result.completed, 1)
        # The backlog behind the gate is otherwise invisible: discovery never surfaces these runs,
        # so `held` stays 0.
        self.assertEqual(result.gated, 1)
        self.assertEqual(result.held, 0)

    @override_settings(BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS=2)
    def test_budget_is_sliced_per_kind_so_a_person_backlog_cannot_starve_behavioral_runs(self) -> None:
        # Two kinds split the cap one slot each. Both person runs are older than the behavioral one,
        # so under a single shared cap they would take the whole budget. Cohort scope because
        # `cohort_bfr_active_team_kind_uq` forbids two active team-scoped runs of one kind per team.
        first_person, _ = self._make_run(
            ["completed"], kind=CohortBackfillKind.PERSON_PROPERTY, scope=CohortBackfillScope.COHORT
        )
        second_person, _ = self._make_run(
            ["completed"], kind=CohortBackfillKind.PERSON_PROPERTY, scope=CohortBackfillScope.COHORT
        )
        behavioral, _ = self._make_run(["completed"])

        result = finalize_backfill_runs()

        for run in (first_person, second_person, behavioral):
            run.refresh_from_db()
        self.assertEqual(result.completed, 2)
        self.assertEqual(first_person.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(behavioral.status, CohortBackfillRunStatus.COMPLETED)
        # The slice still truncates, so a pass stays bounded in the runs it walks and the older
        # person backlog does not take the behavioral slot.
        self.assertEqual(second_person.status, CohortBackfillRunStatus.RECONCILING)

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

    @parameterized.expand([("unset", ""), ("all", "all"), ("uppercase", "ALL"), ("star", "*")])
    def test_run_allowlist_keywords_lift_the_restriction(self, _name: str, raw: str) -> None:
        run, _ = self._make_run(["completed"])

        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=raw):
            result = finalize_backfill_runs()

        # A fail-closed reading of any of these would silently park the whole backlog on a
        # deployment that never set the value.
        run.refresh_from_db()
        self.assertEqual(run.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(result.not_allowlisted, 0)

    def test_run_allowlist_excludes_a_run_that_is_not_listed(self) -> None:
        listed, listed_cohorts = self._make_run(["completed"], scope=CohortBackfillScope.COHORT)
        unlisted, unlisted_cohorts = self._make_run(["completed"], scope=CohortBackfillScope.COHORT)

        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=str(listed.id)):
            result = finalize_backfill_runs()

        listed.refresh_from_db()
        unlisted.refresh_from_db()
        listed_cohorts[0].refresh_from_db()
        unlisted_cohorts[0].refresh_from_db()
        self.assertEqual(listed.status, CohortBackfillRunStatus.COMPLETED)
        self.assertIsNotNone(listed_cohorts[0].last_backfill_events_at)
        # A stamp cannot be undone, so an unverified run must come out of the pass untouched.
        self.assertEqual(unlisted.status, CohortBackfillRunStatus.RECONCILING)
        self.assertIsNone(unlisted_cohorts[0].last_backfill_events_at)
        self.assertEqual(result.not_allowlisted, 1)

    @parameterized.expand(
        [
            ("none", "none", 0),
            ("all_tokens_malformed", "not-a-uuid", 0),
            ("one_good_token", None, 1),
        ]
    )
    def test_run_allowlist_never_widens_on_a_bad_value(self, _name: str, raw: str | None, expected_stamps: int) -> None:
        run, cohorts = self._make_run(["completed"])
        # `None` stands for "the run's own id alongside a malformed token".
        value = raw if raw is not None else f"{run.id},garbage"

        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=value):
            finalize_backfill_runs()

        cohorts[0].refresh_from_db()
        # A typo in a restriction must not degrade into "every run": widening is the direction that
        # cannot be walked back.
        self.assertEqual(1 if cohorts[0].last_backfill_events_at else 0, expected_stamps)

    @parameterized.expand([("unhyphenated", "hex"), ("uppercase", "upper")])
    def test_run_allowlist_matches_a_pasted_id_in_any_form(self, _name: str, form: str) -> None:
        run, cohorts = self._make_run(["completed"])
        raw = run.id.hex if form == "hex" else str(run.id).upper()

        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=raw):
            finalize_backfill_runs()

        # Comparing raw strings would make an operator's pasted line silently match nothing.
        cohorts[0].refresh_from_db()
        self.assertIsNotNone(cohorts[0].last_backfill_events_at)

    @override_settings(
        BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=False,
        BEHAVIORAL_BACKFILL_FINALIZER_MAX_RUNS_PER_PASS=2,
    )
    def test_excluded_runs_do_not_consume_the_per_kind_budget(self) -> None:
        excluded = [self._make_run(["completed"], scope=CohortBackfillScope.COHORT)[0] for _ in range(5)]
        CohortBackfillRun.objects.for_team(self.team.id).filter(id__in=[run.id for run in excluded]).update(
            reconcile_observed_at=timezone.now() - timedelta(days=1)
        )
        allowlisted, cohorts = self._make_run(["completed"], scope=CohortBackfillScope.COHORT)

        with override_settings(BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=str(allowlisted.id)):
            finalize_backfill_runs()

        # The budget slice is applied in SQL. A Python post-filter would let these five older
        # exclusions eat the whole pass and the verified run would never be stamped.
        allowlisted.refresh_from_db()
        cohorts[0].refresh_from_db()
        self.assertEqual(allowlisted.status, CohortBackfillRunStatus.COMPLETED)
        self.assertIsNotNone(cohorts[0].last_backfill_events_at)
