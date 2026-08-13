from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.observe import publish_backfill_run_gauges
from products.cohorts.backend.models.backfill import (
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)


class TestBackfillObservation(BaseTest):
    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization, name="other")

    def _run(
        self,
        *,
        status: str = CohortBackfillRunStatus.SEEDING,
        kind: str = CohortBackfillKind.BEHAVIORAL,
        created_at: object | None = None,
        finished_at: object | None = None,
        team: Team | None = None,
    ) -> CohortBackfillRun:
        team_id = (team or self.team).id
        run = CohortBackfillRun.objects.for_team(team_id).create(
            team_id=team_id,
            backfill_kind=kind,
            trigger_kind=CohortBackfillTrigger.TEAM_ENABLEMENT,
            scope=CohortBackfillScope.TEAM,
            status=status,
            timezone="UTC",
            finished_at=finished_at,
        )
        if created_at is not None:
            CohortBackfillRun.objects.for_team(team_id).filter(id=run.id).update(created_at=created_at)
            run.refresh_from_db()
        return run

    def test_publishes_zeroes_for_empty_slices(self) -> None:
        # A gauge only written when its slice is non-empty freezes at its last reading once the
        # slice drains, leaving a stalled-run alert lit long after the run finished.
        result = publish_backfill_run_gauges()

        self.assertEqual(set(result.active_runs.values()), {0})
        self.assertEqual(set(result.oldest_active_age_seconds.values()), {0.0})
        self.assertEqual(set(result.failed_chunks.values()), {0})
        self.assertEqual(set(result.recent_runs.values()), {0})
        self.assertEqual(len(result.active_runs), 8)  # 4 active statuses x 2 kinds

    def test_counts_active_runs_and_their_age_per_kind(self) -> None:
        # The second behavioral run lives on another team: these gauges serve the whole fleet, and
        # the active-team-kind constraint allows only one per team anyway.
        now = timezone.now()
        self._run(kind=CohortBackfillKind.BEHAVIORAL, created_at=now - timedelta(hours=3))
        self._run(kind=CohortBackfillKind.BEHAVIORAL, created_at=now - timedelta(hours=1), team=self._other_team())
        self._run(kind=CohortBackfillKind.PERSON_PROPERTY, created_at=now - timedelta(minutes=5))

        result = publish_backfill_run_gauges()

        seeding = CohortBackfillRunStatus.SEEDING
        self.assertEqual(result.active_runs[(seeding, CohortBackfillKind.BEHAVIORAL)], 2)
        self.assertEqual(result.active_runs[(seeding, CohortBackfillKind.PERSON_PROPERTY)], 1)
        # The oldest, not the newest: a stalled run has to stay visible behind fresher ones.
        self.assertAlmostEqual(
            result.oldest_active_age_seconds[(seeding, CohortBackfillKind.BEHAVIORAL)], 3 * 3600, delta=60
        )
        self.assertEqual(result.active_runs[(CohortBackfillRunStatus.RECONCILING, CohortBackfillKind.BEHAVIORAL)], 0)

    def test_counts_failed_chunks_only_on_still_active_runs(self) -> None:
        active = self._run()
        done = self._run(status=CohortBackfillRunStatus.COMPLETED, finished_at=timezone.now())
        for run in (active, done):
            CohortBackfillChunk.objects.for_team(self.team.id).create(
                run=run,
                team_id=self.team.id,
                day="2026-01-01",
                status=CohortBackfillChunkStatus.FAILED,
            )

        result = publish_backfill_run_gauges()

        # A failed chunk on a terminal run is history; only one on a live run wedges anything.
        self.assertEqual(result.failed_chunks[CohortBackfillKind.BEHAVIORAL], 1)

    def test_recent_runs_window_excludes_older_terminals(self) -> None:
        now = timezone.now()
        self._run(status=CohortBackfillRunStatus.FAILED, finished_at=now - timedelta(minutes=10))
        self._run(status=CohortBackfillRunStatus.FAILED, finished_at=now - timedelta(hours=2))

        result = publish_backfill_run_gauges()

        self.assertEqual(result.recent_runs[(CohortBackfillRunStatus.FAILED, CohortBackfillKind.BEHAVIORAL)], 1)
