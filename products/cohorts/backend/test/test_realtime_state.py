from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

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
        kind: str = CohortBackfillKind.BEHAVIORAL,
        cohort: Cohort | None = None,
        created_at=None,
    ) -> CohortBackfillRun:
        run = CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            cohort=cohort if scope == CohortBackfillScope.COHORT else None,
            backfill_kind=kind,
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
            # The keys are set with `nx=True` and each kind has its own handler, so a cohort
            # created with one leaf kind and edited to add the other inside the five-minute
            # countdown carries a different trigger per kind. The edit is the one that decides.
            (
                "created",
                {CohortBackfillKind.BEHAVIORAL: CohortBackfillTrigger.COHORT_CREATED},
                CohortRealtimeState.BUILDING,
            ),
            (
                "edited",
                {CohortBackfillKind.BEHAVIORAL: CohortBackfillTrigger.COHORT_EDITED},
                CohortRealtimeState.REBUILDING,
            ),
            (
                "created_then_edited",
                {
                    CohortBackfillKind.BEHAVIORAL: CohortBackfillTrigger.COHORT_CREATED,
                    CohortBackfillKind.PERSON_PROPERTY: CohortBackfillTrigger.COHORT_EDITED,
                },
                CohortRealtimeState.REBUILDING,
            ),
        ]
    )
    def test_debounced_save_reads_as_a_build_before_its_run_exists(
        self, _name: str, triggers: dict[str, str], expected: str
    ) -> None:
        # The run-creation task waits five minutes. Without the debounce key, every cohort would
        # read as needs_attention for those five minutes, right after the save that asked for it.
        leaves = [BEHAVIORAL_LEAF] + ([PERSON_LEAF] if len(triggers) > 1 else [])
        cohort = self._cohort(filters=filters(*leaves))
        for kind, trigger in triggers.items():
            get_redis_client().set(cohort_backfill_pending_key(cohort.id, kind), trigger, ex=300)

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

    def test_a_superseded_participation_does_not_report_the_build_it_left(self) -> None:
        # Editing a cohort a team run is building supersedes only its participation; the run keeps
        # running for the rest of the team. Reading that row would show the abandoned build and
        # hide the rebuild the edit just queued.
        cohort = self._cohort()
        participation = self._participate(self._run(scope=CohortBackfillScope.TEAM), cohort)
        CohortBackfillRunCohort.objects.for_team(self.team.id).filter(id=participation.id).update(
            superseded_at=timezone.now()
        )
        get_redis_client().set(
            cohort_backfill_pending_key(cohort.id, CohortBackfillKind.BEHAVIORAL),
            CohortBackfillTrigger.COHORT_EDITED,
            ex=300,
        )

        assert self._state(cohort) == CohortRealtimeState.REBUILDING

    def test_a_cohort_waiting_on_two_kinds_shows_the_one_furthest_behind(self) -> None:
        # Both stamps gate flag targeting, so the cohort is only as far along as its slower build.
        cohort = self._cohort(filters=filters(BEHAVIORAL_LEAF, PERSON_LEAF))
        self._participate(self._run(status=CohortBackfillRunStatus.RECONCILING, cohort=cohort), cohort)
        self._participate(
            self._run(status=CohortBackfillRunStatus.SEEDING, kind=CohortBackfillKind.PERSON_PROPERTY, cohort=cohort),
            cohort,
        )

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.phase == CohortHistoryBuildPhase.SCANNING

    def test_a_kind_parked_on_an_operator_stops_the_build_reading_as_in_progress(self) -> None:
        # A blocked run needs a person, so a cohort waiting on one is not making progress however
        # well its other kind is going.
        cohort = self._cohort(filters=filters(BEHAVIORAL_LEAF, PERSON_LEAF))
        self._participate(self._run(status=CohortBackfillRunStatus.SEEDING, cohort=cohort), cohort)
        self._participate(
            self._run(status=CohortBackfillRunStatus.BLOCKED, kind=CohortBackfillKind.PERSON_PROPERTY, cohort=cohort),
            cohort,
        )

        assert self._state(cohort) == CohortRealtimeState.NEEDS_ATTENTION

    def test_a_required_kind_with_nothing_building_it_is_not_hidden_by_the_other_one(self) -> None:
        # Both kinds are triggered separately, so one can be refused or lost while the other runs.
        # Reporting the running one as the cohort's progress would leave a bar climbing towards a
        # ready state the missing kind is never going to allow.
        cohort = self._cohort(filters=filters(BEHAVIORAL_LEAF, PERSON_LEAF))
        self._participate(self._run(status=CohortBackfillRunStatus.SEEDING, cohort=cohort), cohort)

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == CohortRealtimeState.NEEDS_ATTENTION
        assert readiness.build is None

        get_redis_client().set(
            cohort_backfill_pending_key(cohort.id, CohortBackfillKind.PERSON_PROPERTY),
            CohortBackfillTrigger.COHORT_CREATED,
            ex=300,
        )
        assert self._state(cohort) == CohortRealtimeState.BUILDING

    def test_a_run_for_a_kind_the_filters_no_longer_need_decides_nothing(self) -> None:
        # A person run left over from an earlier definition is not something this cohort waits on,
        # so neither its progress nor its being blocked describes the cohort.
        cohort = self._cohort()
        self._participate(
            self._run(status=CohortBackfillRunStatus.BLOCKED, kind=CohortBackfillKind.PERSON_PROPERTY, cohort=cohort),
            cohort,
        )
        self._participate(self._run(status=CohortBackfillRunStatus.SEEDING, cohort=cohort), cohort)

        readiness = resolve_realtime_readiness([cohort])[cohort.id]
        assert readiness.state == CohortRealtimeState.BUILDING
        assert readiness.build is not None
        assert readiness.build.phase == CohortHistoryBuildPhase.SCANNING

    def test_the_build_timestamp_follows_chunk_progress(self) -> None:
        # Confirming a chunk never touches the run row, so reporting the run's own timestamp would
        # leave the page claiming no progress for hours while the percentage climbed.
        cohort = self._cohort()
        run = self._run(cohort=cohort)
        self._participate(run, cohort)
        self._chunks(run, total=2, confirmed=1)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.updated_at is not None
        assert build.updated_at >= run.updated_at

    def test_a_failed_debounce_lookup_reports_no_state_rather_than_a_wrong_one(self) -> None:
        # Redis is the only record of a queued build, so a lookup that fails cannot tell a cohort
        # nothing is preparing from one whose build task is waiting out its countdown.
        cohort = self._cohort()
        with patch("products.cohorts.backend.realtime_state.get_redis_client", side_effect=RuntimeError("down")):
            assert resolve_realtime_readiness([cohort]) == {}

    def test_scan_progress_comes_from_confirmed_chunks(self) -> None:
        cohort = self._cohort()
        run = self._run(cohort=cohort)
        self._participate(run, cohort)
        self._chunks(run, total=4, confirmed=1)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.percent_complete == 25

    def test_a_run_past_the_scan_reports_no_progress(self) -> None:
        # Reconciling confirms every chunk, so reading the tally there would park the bar at 100%
        # under "checking", which reads as a build that finished and then stalled.
        cohort = self._cohort()
        run = self._run(status=CohortBackfillRunStatus.RECONCILING, cohort=cohort)
        self._participate(run, cohort)
        self._chunks(run, total=4, confirmed=4)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.phase == CohortHistoryBuildPhase.CHECKING
        assert build.percent_complete is None

    def test_scan_progress_rounds_down_so_100_means_finished(self) -> None:
        cohort = self._cohort()
        run = self._run(cohort=cohort)
        self._participate(run, cohort)
        self._chunks(run, total=200, confirmed=199)

        build = resolve_realtime_readiness([cohort])[cohort.id].build
        assert build is not None
        assert build.percent_complete == 99

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

        # The shape right after a save: one cohort on the page is carried by the debounce key
        # alone, so the branch that falls through to Redis runs inside the query budget too.
        queued = self._cohort()
        get_redis_client().set(
            cohort_backfill_pending_key(queued.id, CohortBackfillKind.BEHAVIORAL),
            CohortBackfillTrigger.COHORT_CREATED,
            ex=300,
        )
        cohorts.append(queued)

        with self.assertNumQueries(2):
            readiness = resolve_realtime_readiness(cohorts)
        assert len(readiness) == 6

    def test_a_page_of_settled_cohorts_reads_no_backfill_rows(self) -> None:
        # Stamped, static and daily cohorts are the steady state, so the common page costs nothing.
        settled = [
            self._cohort(last_backfill_events_at=timezone.now()),
            self._cohort(is_static=True, cohort_type=CohortType.STATIC),
            self._cohort(cohort_type=CohortType.BEHAVIORAL),
        ]

        with self.assertNumQueries(0):
            assert len(resolve_realtime_readiness(settled)) == 3
