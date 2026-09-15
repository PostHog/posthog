from datetime import timedelta

from posthog.test.base import BaseTest

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.redis import get_client as get_redis_client

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
from products.cohorts.backend.models.dependencies import cohort_backfill_pending_key
from products.cohorts.backend.realtime_state import (
    CohortHistoryBuildPhase,
    CohortRealtimeState,
    resolve_realtime_readiness,
)

BEHAVIORAL_LEAF: dict = {
    "type": "behavioral",
    "key": "$pageview",
    "event_type": "events",
    "value": "performed_event",
    "time_value": 7,
    "time_interval": "day",
}

PERSON_LEAF: dict = {"type": "person", "key": "email", "value": ["a@example.com"], "operator": "exact"}


def filters(*leaves: dict) -> dict:
    return {"properties": {"type": "AND", "values": list(leaves)}}


@override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="all")
class TestRealtimeReadiness(BaseTest):
    def _cohort(self, **kwargs) -> Cohort:
        defaults = {"team": self.team, "cohort_type": CohortType.REALTIME, "filters": filters(BEHAVIORAL_LEAF)}
        return Cohort.objects.create(**{**defaults, **kwargs})

    def _run(
        self,
        *,
        status: str = CohortBackfillRunStatus.SEEDING,
        trigger: str = CohortBackfillTrigger.COHORT_CREATED,
        scope: str = CohortBackfillScope.COHORT,
        cohort: Cohort | None = None,
        created_at=None,
    ) -> CohortBackfillRun:
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            cohort=cohort if scope == CohortBackfillScope.COHORT else None,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=trigger,
            scope=scope,
            status=status,
            timezone="UTC",
        )
        if created_at is not None:
            CohortBackfillRun.objects.for_team(self.team.id).filter(id=run.id).update(created_at=created_at)
            run.refresh_from_db()
        return run

    def _participate(self, run: CohortBackfillRun, cohort: Cohort) -> CohortBackfillRunCohort:
        return CohortBackfillRunCohort.objects.for_team(self.team.id).create(
            run=run, team_id=self.team.id, cohort=cohort, filters_shape_hash="shape", pinned_filters=cohort.filters
        )

    def _chunks(self, run: CohortBackfillRun, *, total: int, confirmed: int) -> None:
        for index in range(total):
            CohortBackfillChunk.objects.for_team(self.team.id).create(
                run=run,
                team_id=self.team.id,
                day=timezone.now().date() - timedelta(days=index),
                status=(
                    CohortBackfillChunkStatus.CONFIRMED if index < confirmed else CohortBackfillChunkStatus.PENDING
                ),
            )

    def _state(self, cohort: Cohort) -> str | None:
        readiness = resolve_realtime_readiness([cohort]).get(cohort.id)
        return readiness.state if readiness else None

    def test_unstamped_cohort_with_no_run_needs_attention_rather_than_building(self) -> None:
        # The whole point of deriving from a run row: a refused, lost, or never-triggered backfill
        # must not read as work in progress, or the progress bar never ends.
        assert self._state(self._cohort()) == CohortRealtimeState.NEEDS_ATTENTION

    @parameterized.expand(
        [
            (CohortBackfillTrigger.COHORT_CREATED, CohortRealtimeState.BUILDING),
            (CohortBackfillTrigger.COHORT_EDITED, CohortRealtimeState.REBUILDING),
        ]
    )
    def test_debounced_save_reads_as_a_build_before_its_run_exists(self, trigger: str, expected: str) -> None:
        # The run-creation task waits five minutes. Without the debounce key, every cohort would
        # read as needs_attention for those five minutes, right after the save that asked for it.
        cohort = self._cohort()
        get_redis_client().set(cohort_backfill_pending_key(cohort.id, CohortBackfillKind.BEHAVIORAL), trigger, ex=300)

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == expected
        assert readiness.build is not None
        assert readiness.build.phase == CohortHistoryBuildPhase.WAITING
        assert readiness.build.updated_at is None

    def test_a_started_run_outranks_the_debounce_key(self) -> None:
        cohort = self._cohort()
        get_redis_client().set(
            cohort_backfill_pending_key(cohort.id, CohortBackfillKind.BEHAVIORAL),
            CohortBackfillTrigger.COHORT_CREATED,
            ex=300,
        )
        self._participate(self._run(status=CohortBackfillRunStatus.RECONCILING, cohort=cohort), cohort)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.phase == CohortHistoryBuildPhase.CHECKING

    @parameterized.expand(
        [
            (CohortBackfillRunStatus.AWAITING_BOUNDARY, CohortHistoryBuildPhase.WAITING),
            (CohortBackfillRunStatus.SEEDING, CohortHistoryBuildPhase.SCANNING),
            (CohortBackfillRunStatus.RECONCILING, CohortHistoryBuildPhase.CHECKING),
        ]
    )
    def test_active_run_reports_its_phase(self, run_status: str, phase: str) -> None:
        cohort = self._cohort()
        self._participate(self._run(status=run_status, cohort=cohort), cohort)

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == CohortRealtimeState.BUILDING
        assert readiness.build is not None
        assert readiness.build.phase == phase

    @parameterized.expand(
        [
            (CohortBackfillRunStatus.BLOCKED,),
            (CohortBackfillRunStatus.FAILED,),
            (CohortBackfillRunStatus.CANCELLED,),
            (CohortBackfillRunStatus.SUPERSEDED,),
        ]
    )
    def test_run_that_is_not_making_progress_needs_attention(self, run_status: str) -> None:
        cohort = self._cohort()
        self._participate(self._run(status=run_status, cohort=cohort), cohort)

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == CohortRealtimeState.NEEDS_ATTENTION
        assert readiness.build is None

    def test_edit_triggered_run_rebuilds(self) -> None:
        cohort = self._cohort()
        self._participate(self._run(trigger=CohortBackfillTrigger.COHORT_EDITED, cohort=cohort), cohort)

        assert self._state(cohort) == CohortRealtimeState.REBUILDING

    def test_team_run_builds_the_cohorts_participating_in_it(self) -> None:
        # A team enablement run carries no cohort_id, so reading runs instead of participations
        # would leave every cohort it is building reading as needs_attention.
        cohort = self._cohort()
        self._participate(self._run(scope=CohortBackfillScope.TEAM), cohort)

        assert self._state(cohort) == CohortRealtimeState.BUILDING

    def test_scan_progress_comes_from_confirmed_chunks(self) -> None:
        cohort = self._cohort()
        run = self._run(cohort=cohort)
        self._participate(run, cohort)
        self._chunks(run, total=4, confirmed=1)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.percent_complete == 25

    def test_run_with_no_chunks_yet_reports_no_progress(self) -> None:
        cohort = self._cohort()
        self._participate(self._run(cohort=cohort), cohort)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.percent_complete is None

    def test_newest_run_wins_when_a_cohort_has_several(self) -> None:
        cohort = self._cohort()
        now = timezone.now()
        self._participate(
            self._run(status=CohortBackfillRunStatus.FAILED, cohort=cohort, created_at=now - timedelta(hours=2)),
            cohort,
        )
        self._participate(self._run(cohort=cohort, created_at=now), cohort)

        assert self._state(cohort) == CohortRealtimeState.BUILDING

    def test_stamped_cohort_is_ready_and_dates_from_the_stamp_its_filters_need(self) -> None:
        # A behavioral-only cohort can carry a person stamp from an earlier definition. Dating
        # readiness from the later of the two stamps would report a backfill this cohort never used.
        events_stamp = timezone.now() - timedelta(hours=3)
        cohort = self._cohort(last_backfill_events_at=events_stamp, last_backfill_person_properties_at=timezone.now())

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == CohortRealtimeState.READY
        assert readiness.ready_at == events_stamp

    def test_mixed_cohort_is_ready_once_both_stamps_land(self) -> None:
        cohort = self._cohort(filters=filters(BEHAVIORAL_LEAF, PERSON_LEAF), last_backfill_events_at=timezone.now())
        assert self._state(cohort) == CohortRealtimeState.NEEDS_ATTENTION

        cohort.last_backfill_person_properties_at = timezone.now()
        assert self._state(cohort) == CohortRealtimeState.READY

    @parameterized.expand(
        [
            ("static", {"is_static": True, "cohort_type": CohortType.STATIC}, CohortRealtimeState.STATIC),
            ("not_realtime", {"cohort_type": CohortType.BEHAVIORAL}, CohortRealtimeState.DAILY),
            # Flags never gate a person-only cohort on a backfill, so it must not read as unavailable.
            ("person_only", {"filters": filters(PERSON_LEAF)}, None),
        ]
    )
    def test_cohorts_outside_the_realtime_path(self, _name: str, kwargs: dict, expected: str | None) -> None:
        assert self._state(self._cohort(**kwargs)) == expected

    @override_settings(REALTIME_COHORT_TEAM_ALLOWLIST="none")
    def test_team_without_the_pipeline_has_no_realtime_state(self) -> None:
        # Cohort type is computed for every team, so without this gate every cohort in the fleet
        # would claim a realtime state the team's flags can never read.
        cohort = self._cohort()
        with self.assertNumQueries(0):
            assert resolve_realtime_readiness([cohort]) == {}

    def test_resolving_a_page_costs_the_same_queries_as_one_cohort(self) -> None:
        # The cohort list and the flag picker's typeahead both resolve a whole page, so the cost
        # has to be per page, not per row.
        cohorts = []
        for _ in range(5):
            cohort = self._cohort()
            self._participate(self._run(cohort=cohort), cohort)
            cohorts.append(cohort)

        with self.assertNumQueries(2):
            readiness = resolve_realtime_readiness(cohorts)
        assert len(readiness) == 5

    def test_a_page_of_settled_cohorts_reads_no_backfill_rows(self) -> None:
        # Stamped, static and daily cohorts are the steady state, so the common page costs nothing.
        settled = [
            self._cohort(last_backfill_events_at=timezone.now()),
            self._cohort(is_static=True, cohort_type=CohortType.STATIC),
            self._cohort(cohort_type=CohortType.BEHAVIORAL),
        ]

        with self.assertNumQueries(0):
            assert len(resolve_realtime_readiness(settled)) == 3
