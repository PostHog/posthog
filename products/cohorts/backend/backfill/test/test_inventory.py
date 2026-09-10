from datetime import date, timedelta

from posthog.test.base import BaseTest

from django.db import connection
from django.test import SimpleTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized

from posthog.tasks.calculate_cohort import finalize_cohort_backfill_runs  # noqa: F401  breaks an import cycle

from products.cohorts.backend.backfill.finalize import finalize_backfill_runs
from products.cohorts.backend.backfill.inventory import (
    RUN_CLASSIFICATIONS,
    RunFacts,
    allowlist_env_line,
    classify_run,
    collect_run_inventory,
    stampable_now,
)
from products.cohorts.backend.backfill.readiness import ensure_filters_shape_hash
from products.cohorts.backend.models.backfill import (
    ACTIVE_COHORT_BACKFILL_RUN_STATUSES,
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort, CohortType

STALLED_AFTER = timedelta(hours=6)


def _facts(**overrides: object) -> RunFacts:
    defaults: dict[str, object] = {
        "status": CohortBackfillRunStatus.SEEDING,
        "scope": CohortBackfillScope.TEAM,
        "cohort_id": None,
        "participations_total": 1,
        "participations_open": 1,
        "live_participation_cohorts": 1,
        "reconcile_observed_at": None,
        "boundary_established_at": None,
        "chunks_planned_at": None,
        "chunks_total": 0,
        "chunks_unconfirmed": 0,
        "chunks_failed_exhausted": 0,
        "chunk_last_progress_at": None,
        "now": timezone.now(),
        "stalled_after": STALLED_AFTER,
    }
    return RunFacts(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestClassifyRun(SimpleTestCase):
    def test_seeding_run_with_chunks_at_the_attempt_cap_is_stalled(self) -> None:
        now = timezone.now()

        facts = _facts(
            now=now,
            chunks_planned_at=now - timedelta(hours=1),
            chunks_total=3,
            chunks_unconfirmed=1,
            chunks_failed_exhausted=1,
            chunk_last_progress_at=now - timedelta(minutes=1),
        )

        # Recent chunk progress must not rescue a run whose remaining chunk can never be reclaimed:
        # this is the one provably-unclaimable population the cleanup exists to drain.
        self.assertEqual(classify_run(facts), "seeding-stalled")

    def test_seeding_run_with_recent_chunk_progress_is_healthy(self) -> None:
        now = timezone.now()

        facts = _facts(
            now=now,
            chunks_planned_at=now - timedelta(days=30),
            chunks_total=100,
            chunks_unconfirmed=40,
            chunk_last_progress_at=now - timedelta(minutes=2),
        )

        # An old run seeding a long history is healthy, not a cancel target.
        self.assertEqual(classify_run(facts), "seeding-healthy")

    @parameterized.expand([("just_planned", 1, "seeding-healthy"), ("long_planned", 48, "seeding-stalled")])
    def test_zero_chunk_run_is_healthy_until_the_completion_sweep_has_had_time(
        self, _name: str, planned_hours_ago: int, expected: str
    ) -> None:
        now = timezone.now()

        facts = _facts(now=now, chunks_planned_at=now - timedelta(hours=planned_hours_ago), chunks_total=0)

        # A run whose conditions plan no days legitimately stamps `chunks_planned_at` with zero
        # chunks. Without the grace period it reads as stalled the instant it is planned, and the
        # default terminalize sweep cancels a backfill the seeder was about to complete.
        self.assertEqual(classify_run(facts), expected)

    @parameterized.expand(
        [
            ("cohort_hard_deleted", {"scope": CohortBackfillScope.COHORT, "cohort_id": None}),
            ("no_participations", {"participations_total": 0}),
            ("all_cohorts_deleted", {"live_participation_cohorts": 0}),
            ("all_participations_resolved", {"participations_open": 0}),
        ]
    )
    def test_orphan_precedes_the_status_buckets(self, _name: str, overrides: dict) -> None:
        # Each of these can never finalize, so the status it happens to sit in is not the answer.
        facts = _facts(status=CohortBackfillRunStatus.RECONCILING, reconcile_observed_at=timezone.now(), **overrides)

        self.assertEqual(classify_run(facts), "orphaned")

    @parameterized.expand([(status,) for status in ACTIVE_COHORT_BACKFILL_RUN_STATUSES])
    def test_every_active_status_has_a_classification(self, status: str) -> None:
        # A status added to the vocabulary without a bucket would otherwise fall through to
        # `awaiting-boundary` and read as harmless.
        self.assertIn(classify_run(_facts(status=status)), RUN_CLASSIFICATIONS)


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="all",
    BEHAVIORAL_BACKFILL_FINALIZER_ENABLED=True,
    BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=True,
    BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST="all",
)
class TestCollectRunInventory(BaseTest):
    def _cohort(self, name: str = "realtime", team_id: int | None = None) -> Cohort:
        cohort = Cohort.objects.create(
            team_id=team_id or self.team.id,
            name=name,
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event_multiple",
                            "conditionHash": "hash",
                            "time_value": 7,
                            "time_interval": "day",
                            "operator": "gte",
                            "operator_value": 2,
                        }
                    ],
                }
            },
        )
        ensure_filters_shape_hash(cohort)
        cohort.refresh_from_db()
        return cohort

    def _run(
        self,
        *,
        team_id: int | None = None,
        status: str = CohortBackfillRunStatus.SEEDING,
        kind: str = CohortBackfillKind.BEHAVIORAL,
        observed: bool = False,
        cohort: Cohort | None = None,
    ) -> CohortBackfillRun:
        team_id = team_id or self.team.id
        # Cohort scope so several runs can coexist: only one team-scoped run per kind may be active.
        cohort = cohort or self._cohort(f"cohort-{CohortBackfillRun.objects.unscoped().count()}", team_id=team_id)
        run = CohortBackfillRun.objects.for_team(team_id).create(
            team_id=team_id,
            backfill_kind=kind,
            trigger_kind=CohortBackfillTrigger.COHORT_CREATED,
            scope=CohortBackfillScope.COHORT,
            cohort=cohort,
            status=status,
            reconcile_observed_at=timezone.now() if observed else None,
            timezone="UTC",
        )
        CohortBackfillRunCohort.objects.for_team(team_id).create(
            run=run,
            team_id=team_id,
            cohort=cohort,
            filters_shape_hash=cohort.filters_shape_hash or "",
            behavioral_filters_shape_hash=cohort.behavioral_filters_shape_hash or "",
            person_filters_shape_hash=cohort.person_filters_shape_hash or "",
            pinned_filters=cohort.filters,
            reconcile_completed_at=timezone.now() if observed else None,
        )
        return run

    def test_finalizable_rows_are_exactly_what_the_finalizer_stamps(self) -> None:
        finalizable = self._run(status=CohortBackfillRunStatus.RECONCILING, observed=True)
        unobserved = self._run(status=CohortBackfillRunStatus.RECONCILING, observed=False)

        rows = {row.run_id: row.classification for row in collect_run_inventory(stalled_after=STALLED_AFTER)}
        self.assertEqual(rows[finalizable.id], "finalizable")
        self.assertEqual(rows[unobserved.id], "awaiting-observation")

        # The bucket is only useful if it predicts the finalizer, so assert against the finalizer
        # itself rather than restating its predicate.
        finalize_backfill_runs()
        finalizable.refresh_from_db()
        unobserved.refresh_from_db()
        self.assertEqual(finalizable.status, CohortBackfillRunStatus.COMPLETED)
        self.assertEqual(unobserved.status, CohortBackfillRunStatus.RECONCILING)

    def test_inventory_covers_every_team(self) -> None:
        other_team = self.organization.teams.create(name="other")
        mine = self._run()
        theirs = self._run(team_id=other_team.id)

        run_ids = {row.run_id for row in collect_run_inventory(stalled_after=STALLED_AFTER)}

        # A per-team read would silently produce a verified list that is a subset of what the
        # finalizer, which scans every team, will stamp.
        self.assertEqual(run_ids, {mine.id, theirs.id})

    def test_query_count_does_not_grow_with_the_run_count(self) -> None:
        self._run()
        with CaptureQueriesContext(connection) as one_run:
            collect_run_inventory(stalled_after=STALLED_AFTER)

        for _ in range(9):
            self._run()
        with CaptureQueriesContext(connection) as ten_runs:
            collect_run_inventory(stalled_after=STALLED_AFTER)

        # The prod active set is large, so an N+1 makes the command unusable mid-cleanup.
        self.assertEqual(len(ten_runs.captured_queries), len(one_run.captured_queries))

    def test_stalled_chunk_tally_respects_the_attempt_cap_and_lease(self) -> None:
        run = self._run()
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            chunks_planned_at=timezone.now() - timedelta(hours=1)
        )
        chunk = CohortBackfillChunk.objects.for_team(self.team.id).create(
            run=run,
            team_id=self.team.id,
            day=date(2026, 1, 1),
            status=CohortBackfillChunkStatus.FAILED,
            attempts=5,
            lease_expires_at=timezone.now() + timedelta(minutes=5),
        )

        # Still leased, so the seeder may yet reclaim it.
        [row] = collect_run_inventory(stalled_after=STALLED_AFTER)
        self.assertEqual(row.classification, "seeding-healthy")

        CohortBackfillChunk.objects.for_team(self.team.id).filter(id=chunk.id).update(
            lease_expires_at=timezone.now() - timedelta(minutes=5)
        )
        [row] = collect_run_inventory(stalled_after=STALLED_AFTER)
        self.assertEqual(row.classification, "seeding-stalled")
        self.assertEqual(row.chunks_failed_exhausted, 1)

    @override_settings(BEHAVIORAL_BACKFILL_PERSON_READINESS_ENABLED=False)
    def test_person_runs_held_by_the_readiness_gate_are_kept_off_the_allowlist_line(self) -> None:
        behavioral = self._run(status=CohortBackfillRunStatus.RECONCILING, observed=True)
        self._run(status=CohortBackfillRunStatus.RECONCILING, observed=True, kind=CohortBackfillKind.PERSON_PROPERTY)

        rows = collect_run_inventory(stalled_after=STALLED_AFTER)

        # Both are finalizable by column, but the finalizer's kind filter cannot see the person one,
        # so putting it on the allowlist would stamp it whenever that gate opens instead of now.
        self.assertEqual([row.run_id for row in stampable_now(rows)], [behavioral.id])
        self.assertEqual(
            allowlist_env_line(stampable_now(rows)),
            f"BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST={behavioral.id}",
        )

    def test_allowlist_line_says_none_when_there_is_nothing_to_stamp(self) -> None:
        # An empty value reads as "every run", the opposite of what an operator who verified nothing
        # means.
        self.assertEqual(allowlist_env_line([]), "BEHAVIORAL_BACKFILL_FINALIZER_RUN_ALLOWLIST=none")
