from datetime import UTC, date, datetime

from posthog.test.base import BaseTest

from django.test import override_settings

from products.cohorts.backend.models.backfill import (
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
from products.cohorts.backend.parity.oracle import load_run_context

_CONFIRMED = CohortBackfillChunkStatus.CONFIRMED
_PENDING = CohortBackfillChunkStatus.PENDING


# Allowlist "none" so creating a realtime cohort does not auto-enqueue a backfill run that would
# collide with the runs each test builds by hand.
@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none")
class TestLoadRunContext(BaseTest):
    def _cohort(self) -> Cohort:
        cohort = Cohort.objects.create(
            team=self.team,
            name="c",
            cohort_type=CohortType.REALTIME,
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "event_type": "events",
                            "value": "performed_event",
                            "conditionHash": "hash",
                            "time_value": 7,
                            "time_interval": "day",
                            "bytecode": ["_H", 1],
                        }
                    ],
                }
            },
        )
        cohort.refresh_from_db()
        return cohort

    def _run(self, *, boundary_at: datetime | None, timezone: str = "UTC") -> CohortBackfillRun:
        return CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=CohortBackfillTrigger.TEAM_ENABLEMENT,
            scope=CohortBackfillScope.TEAM,
            status=CohortBackfillRunStatus.SEEDING,
            timezone=timezone,
            boundary_at=boundary_at,
            pinned={},
            preconditions={},
        )

    def _participation(self, run: CohortBackfillRun, cohort: Cohort, behavioral_hash: str) -> None:
        CohortBackfillRunCohort.objects.for_team(self.team.id).create(
            run=run,
            team_id=self.team.id,
            cohort=cohort,
            filters_shape_hash="shape",
            behavioral_filters_shape_hash=behavioral_hash,
            pinned_filters=cohort.filters,
        )

    def _chunk(self, run: CohortBackfillRun, day: date, band: int, status: str) -> None:
        CohortBackfillChunk.objects.for_team(self.team.id).create(
            run=run, team_id=self.team.id, day=day, band=band, status=status
        )

    def test_loads_seeding_run_and_confirms_only_fully_seeded_days(self) -> None:
        # A run stuck in `seeding` (B5 absent) must still load — no status filter — and a day counts as
        # a confirmed seed domain only when every band chunk is CONFIRMED. Accessing run_cohorts/chunks
        # through the fail-closed reverse relation would raise TeamScopeError here, so a clean load also
        # guards that regression.
        cohort = self._cohort()
        run = self._run(boundary_at=datetime(2026, 7, 21, 20, 40, tzinfo=UTC))
        self._participation(run, cohort, cohort.behavioral_filters_shape_hash or "")
        self._chunk(run, date(2026, 7, 19), 0, _CONFIRMED)
        self._chunk(run, date(2026, 7, 19), 1, _CONFIRMED)
        self._chunk(run, date(2026, 7, 20), 0, _CONFIRMED)
        self._chunk(run, date(2026, 7, 20), 1, _PENDING)  # day 20 only partially seeded

        ctx = load_run_context(self.team.id, cohort.id, None)

        assert ctx is not None
        self.assertEqual(ctx.run_id, str(run.id))
        self.assertEqual(ctx.status, CohortBackfillRunStatus.SEEDING)
        self.assertEqual(ctx.boundary_day, date(2026, 7, 21))
        self.assertEqual(ctx.confirmed_days, frozenset({date(2026, 7, 19)}))
        self.assertEqual(ctx.non_confirmed_chunks, 1)
        self.assertFalse(ctx.shape_hash_drift)

    def test_boundary_day_uses_run_timezone(self) -> None:
        # 2026-07-21T02:00Z is 2026-07-20 19:00 in US/Pacific, so the boundary calendar day is the 20th.
        cohort = self._cohort()
        run = self._run(boundary_at=datetime(2026, 7, 21, 2, 0, tzinfo=UTC), timezone="US/Pacific")
        self._participation(run, cohort, cohort.behavioral_filters_shape_hash or "")

        ctx = load_run_context(self.team.id, cohort.id, None)

        assert ctx is not None
        self.assertEqual(ctx.run_timezone, "US/Pacific")
        self.assertEqual(ctx.boundary_day, date(2026, 7, 20))

    def test_shape_hash_drift_when_pinned_hash_differs_from_current(self) -> None:
        cohort = self._cohort()
        run = self._run(boundary_at=datetime(2026, 7, 21, 20, 40, tzinfo=UTC))
        self._participation(run, cohort, "stale-hash-from-before-an-edit")

        ctx = load_run_context(self.team.id, cohort.id, None)

        assert ctx is not None
        self.assertTrue(ctx.shape_hash_drift)

    def test_returns_none_when_no_run_has_a_boundary(self) -> None:
        cohort = self._cohort()
        run = self._run(boundary_at=None)  # awaiting boundary
        self._participation(run, cohort, "")

        self.assertIsNone(load_run_context(self.team.id, cohort.id, None))
