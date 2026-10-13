from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from prometheus_client import CollectorRegistry

from posthog.models.team.team import Team

from products.cohorts.backend.backfill.observe import PUSH_JOB_NAME, publish_backfill_run_gauges
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
    def setUp(self) -> None:
        super().setUp()
        # Assert on what the push carries, not on the pass that fed it: the gauges are the only
        # output anything downstream sees, and deleting the publish step has to fail a test.
        self.registry = CollectorRegistry()

        @contextmanager
        def _capture(job_name: str) -> Iterator[CollectorRegistry]:
            self.assertEqual(job_name, PUSH_JOB_NAME)
            # A fresh registry per push, as the real helper does, so a second pass in one test does
            # not collide with the first pass's gauges.
            self.registry = CollectorRegistry()
            yield self.registry

        patcher = patch("products.cohorts.backend.backfill.observe.pushed_metrics_registry", _capture)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _gauge(self, name: str, **labels: str) -> float | None:
        return self.registry.get_sample_value(name, labels)

    def _other_team(self) -> Team:
        return Team.objects.create(organization=self.organization, name="other")

    def _run(
        self,
        *,
        status: str = CohortBackfillRunStatus.SEEDING,
        kind: str = CohortBackfillKind.BEHAVIORAL,
        created_at: datetime | None = None,
        finished_at: datetime | None = None,
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
        publish_backfill_run_gauges()

        seeding = CohortBackfillRunStatus.SEEDING
        self.assertEqual(
            self._gauge("posthog_cohort_backfill_runs_active", status=seeding, kind=CohortBackfillKind.BEHAVIORAL), 0.0
        )
        self.assertEqual(self._gauge("posthog_cohort_backfill_chunks_failed", kind=CohortBackfillKind.BEHAVIORAL), 0.0)
        self.assertEqual(
            self._gauge(
                "posthog_cohort_backfill_runs_recent",
                status=CohortBackfillRunStatus.FAILED,
                kind=CohortBackfillKind.PERSON_PROPERTY,
            ),
            0.0,
        )
        published = [
            sample
            for metric in self.registry.collect()
            for sample in metric.samples
            if sample.name == "posthog_cohort_backfill_runs_active"
        ]
        self.assertEqual(len(published), 8)  # 4 active statuses x 2 kinds

    def test_gauges_fall_back_to_zero_when_a_slice_drains(self) -> None:
        # The freeze this guards against: a slice written only while it is non-empty keeps reporting
        # the finished run's age, holding a stalled-run alert lit hours after the run ended.
        now = timezone.now()
        run = self._run(created_at=now - timedelta(hours=3))
        labels = {"status": CohortBackfillRunStatus.SEEDING, "kind": CohortBackfillKind.BEHAVIORAL}

        publish_backfill_run_gauges()

        self.assertEqual(self._gauge("posthog_cohort_backfill_runs_active", **labels), 1.0)
        self.assertAlmostEqual(
            self._gauge("posthog_cohort_backfill_oldest_active_run_age_seconds", **labels) or 0.0,
            3 * 3600,
            delta=60,
        )

        CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(
            status=CohortBackfillRunStatus.COMPLETED, finished_at=now
        )
        publish_backfill_run_gauges()

        self.assertEqual(self._gauge("posthog_cohort_backfill_runs_active", **labels), 0.0)
        self.assertEqual(self._gauge("posthog_cohort_backfill_oldest_active_run_age_seconds", **labels), 0.0)
        self.assertEqual(
            self._gauge(
                "posthog_cohort_backfill_runs_recent",
                status=CohortBackfillRunStatus.COMPLETED,
                kind=CohortBackfillKind.BEHAVIORAL,
            ),
            1.0,
        )

    def test_counts_active_runs_and_their_age_per_kind(self) -> None:
        # The second behavioral run lives on another team: these gauges serve the whole fleet, and
        # the active-team-kind constraint allows only one per team anyway.
        now = timezone.now()
        self._run(kind=CohortBackfillKind.BEHAVIORAL, created_at=now - timedelta(hours=3))
        self._run(kind=CohortBackfillKind.BEHAVIORAL, created_at=now - timedelta(hours=1), team=self._other_team())
        self._run(kind=CohortBackfillKind.PERSON_PROPERTY, created_at=now - timedelta(minutes=5))

        publish_backfill_run_gauges()

        seeding = CohortBackfillRunStatus.SEEDING
        behavioral = {"status": seeding, "kind": CohortBackfillKind.BEHAVIORAL}
        self.assertEqual(self._gauge("posthog_cohort_backfill_runs_active", **behavioral), 2.0)
        self.assertEqual(
            self._gauge("posthog_cohort_backfill_runs_active", status=seeding, kind=CohortBackfillKind.PERSON_PROPERTY),
            1.0,
        )
        # The oldest, not the newest: a stalled run has to stay visible behind fresher ones.
        self.assertAlmostEqual(
            self._gauge("posthog_cohort_backfill_oldest_active_run_age_seconds", **behavioral) or 0.0,
            3 * 3600,
            delta=60,
        )
        self.assertEqual(
            self._gauge(
                "posthog_cohort_backfill_runs_active",
                status=CohortBackfillRunStatus.RECONCILING,
                kind=CohortBackfillKind.BEHAVIORAL,
            ),
            0.0,
        )

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

        publish_backfill_run_gauges()

        # A failed chunk on a terminal run is history; only one on a live run means retry churn.
        self.assertEqual(self._gauge("posthog_cohort_backfill_chunks_failed", kind=CohortBackfillKind.BEHAVIORAL), 1.0)

    def test_recent_runs_window_excludes_older_terminals(self) -> None:
        now = timezone.now()
        self._run(status=CohortBackfillRunStatus.FAILED, finished_at=now - timedelta(minutes=10))
        self._run(status=CohortBackfillRunStatus.FAILED, finished_at=now - timedelta(hours=2))

        publish_backfill_run_gauges()

        self.assertEqual(
            self._gauge(
                "posthog_cohort_backfill_runs_recent",
                status=CohortBackfillRunStatus.FAILED,
                kind=CohortBackfillKind.BEHAVIORAL,
            ),
            1.0,
        )
