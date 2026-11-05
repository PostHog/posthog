from datetime import UTC, date, datetime
from typing import Any

from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from products.cohorts.backend.backfill.flag_calls_table import FlagCallsTable
from products.cohorts.backend.backfill.runs import create_team_backfill_run
from products.cohorts.backend.backfill.sizing import BehavioralScanEstimate, PersonSeedEstimate
from products.cohorts.backend.models.backfill import (
    CohortBackfillKind,
    CohortBackfillRun,
    CohortBackfillRunCohort,
    CohortBackfillRunStatus,
    CohortBackfillScope,
    CohortBackfillTrigger,
)
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_enablement import (
    CohortRefusal,
    RunAlreadyCreated,
    RunCreated,
    RunRefused,
    TeamEnablement,
    enable_realtime_cohorts,
)

PERSON_LEAF = {"type": "person", "key": "email", "operator": "exact", "value": "person@example.com"}
PAGEVIEW_LEAF = {
    "type": "behavioral",
    "key": "$pageview",
    "value": "performed_event",
    "event_type": "events",
    "time_value": 7,
    "time_interval": "day",
}


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="none",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
    BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY=1_000,
)
class TestEnableRealtimeCohorts(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.peak_day_events = 500
        scan = mock.patch(
            "products.cohorts.backend.realtime_enablement.estimate_behavioral_scan_events",
            side_effect=self._scan_estimate,
        )
        sizing = mock.patch(
            "products.cohorts.backend.backfill.runs.estimate_person_seed_topic_bytes",
            return_value=PersonSeedEstimate(
                estimated_persons=10,
                pinned_condition_count=1,
                bytes_per_seed=294,
                estimated_topic_bytes=2_940,
                budget_bytes=1_000_000,
            ),
        )
        for patcher in (scan, sizing):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _scan_estimate(
        self, team_id: int, event_names: list[str], *, flag_calls_table: FlagCallsTable, max_events_per_day: int
    ) -> BehavioralScanEstimate:
        return BehavioralScanEstimate(
            days_sampled=7,
            peak_day=date(2026, 11, 1),
            peak_day_events=self.peak_day_events,
            peak_day_events_by_name={"$pageview": self.peak_day_events},
            max_events_per_day=max_events_per_day,
        )

    def _cohort(self, *leaves: dict[str, Any]) -> Cohort:
        cohort = Cohort.objects.create(team=self.team, filters={"properties": {"type": "AND", "values": list(leaves)}})
        # Cohorts saved before the column existed have no `condition_type`.
        Cohort.objects.filter(id=cohort.id).update(condition_type=None)
        return cohort

    def _level(self) -> str:
        return RealtimeCohortTeamAccess.objects.get(team=self.team).level

    def _team_runs(self, kind: CohortBackfillKind) -> list[CohortBackfillRun]:
        return list(CohortBackfillRun.objects.for_team(self.team.id).filter(backfill_kind=kind))

    def _enable(self) -> TeamEnablement:
        enablement = enable_realtime_cohorts(self.team.id, purpose=RealtimeCohortAccessPurpose.BETA)
        assert isinstance(enablement, TeamEnablement)
        return enablement

    def test_enables_a_team_in_one_call(self) -> None:
        mixed = self._cohort(PERSON_LEAF, PAGEVIEW_LEAF)
        person_only = self._cohort(PERSON_LEAF)
        # The API accepts a behavioral leaf with no time window, and the catalog drops it.
        windowless = self._cohort({key: value for key, value in PAGEVIEW_LEAF.items() if not key.startswith("time_")})
        CohortBackfillRun.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            trigger_kind=CohortBackfillTrigger.TEAM_ENABLEMENT,
            scope=CohortBackfillScope.TEAM,
            status=CohortBackfillRunStatus.COMPLETED,
            timezone="UTC",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        enablement = self._enable()

        access = RealtimeCohortTeamAccess.objects.get(team=self.team)
        assert (access.level, access.purpose, access.save_triggers_backfill) == (
            RealtimeCohortLevel.SERVING,
            RealtimeCohortAccessPurpose.BETA,
            True,
        )
        cohorts = list(Cohort.objects.filter(team=self.team).order_by("id"))
        assert [cohort.condition_type and cohort.condition_type["behavioral"] for cohort in cohorts] == [
            True,
            False,
            True,
        ]
        assert all(
            None
            not in (cohort.filters_shape_hash, cohort.behavioral_filters_shape_hash, cohort.person_filters_shape_hash)
            for cohort in cohorts
        )

        assert isinstance(enablement.behavioral, RunCreated)
        assert isinstance(enablement.person, RunCreated)
        runs = CohortBackfillRun.objects.for_team(self.team.id)
        behavioral_run = runs.get(id=enablement.behavioral.run_id)
        person_run = runs.get(id=enablement.person.run_id)
        assert {(run.scope, run.status, run.trigger_kind) for run in (behavioral_run, person_run)} == {
            (CohortBackfillScope.TEAM, CohortBackfillRunStatus.AWAITING_BOUNDARY, CohortBackfillTrigger.TEAM_ENABLEMENT)
        }
        participations = CohortBackfillRunCohort.objects.for_team(self.team.id)
        assert sorted(participations.filter(run=behavioral_run).values_list("cohort_id", flat=True)) == [mixed.id]
        assert sorted(participations.filter(run=person_run).values_list("cohort_id", flat=True)) == [
            mixed.id,
            person_only.id,
        ]
        assert enablement.refused_cohorts == (
            CohortRefusal(
                cohort_id=windowless.id,
                kind=CohortBackfillKind.BEHAVIORAL,
                reason="has a filter the realtime catalog drops (unsupported_state_variant)",
            ),
        )
        assert enablement.unclassified_cohort_ids == ()

    def test_a_refused_run_keeps_the_team_processing_until_a_rerun_finds_both_runs(self) -> None:
        self._cohort(PERSON_LEAF, PAGEVIEW_LEAF)
        self.peak_day_events = 2_000

        first = self._enable()

        assert isinstance(first.behavioral, RunRefused)
        assert "2000 events on its busiest day (2026-11-01), above the limit of 1000" in first.behavioral.reason
        [person_run] = self._team_runs(CohortBackfillKind.PERSON_PROPERTY)
        assert first.person == RunCreated(run_id=person_run.id)
        assert self._team_runs(CohortBackfillKind.BEHAVIORAL) == []
        assert self._level() == RealtimeCohortLevel.PROCESSING

        # The person run finishes while the operator accepts the scan volume through
        # `create_cohort_backfill_run --max-scan-events-per-day 0`.
        CohortBackfillRun.objects.for_team(self.team.id).filter(id=person_run.id).update(
            status=CohortBackfillRunStatus.COMPLETED
        )
        behavioral_run = create_team_backfill_run(self.team.id, CohortBackfillTrigger.TEAM_ENABLEMENT)
        second = self._enable()

        assert (second.behavioral, second.person) == (
            RunAlreadyCreated(run_id=behavioral_run.id),
            RunAlreadyCreated(run_id=person_run.id),
        )
        assert self._level() == RealtimeCohortLevel.SERVING
        assert CohortBackfillRun.objects.for_team(self.team.id).count() == 2

    @override_settings(BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=False)
    def test_missing_attestations_refuse_the_team_before_any_write(self) -> None:
        cohort = self._cohort(PERSON_LEAF, PAGEVIEW_LEAF)

        with self.assertRaisesMessage(ValueError, "Missing operator attestations: processor durability"):
            enable_realtime_cohorts(self.team.id, purpose=RealtimeCohortAccessPurpose.BETA)

        assert not RealtimeCohortTeamAccess.objects.filter(team=self.team).exists()
        assert not CohortBackfillRun.objects.for_team(self.team.id).exists()
        assert Cohort.objects.get(id=cohort.id).condition_type is None
