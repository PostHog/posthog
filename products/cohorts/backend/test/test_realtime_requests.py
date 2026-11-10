from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest import mock

from django.test import override_settings

from parameterized import parameterized

from products.cohorts.backend.backfill.flag_calls_table import FlagCallsTable
from products.cohorts.backend.backfill.sizing import BehavioralScanEstimate, PersonSeedEstimate
from products.cohorts.backend.models.backfill import CohortBackfillKind, CohortBackfillRun
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.realtime_request import RealtimeCohortRequest, RealtimeCohortRequestState
from products.cohorts.backend.models.team_access import (
    RealtimeCohortAccessPurpose,
    RealtimeCohortLevel,
    RealtimeCohortTeamAccess,
)
from products.cohorts.backend.realtime_requests import (
    REQUEST_STALE_AFTER,
    process_request,
    submit_backfill,
    submit_enablement,
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
SUBMITTED_AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@override_settings(
    REALTIME_COHORT_TEAM_ALLOWLIST="none",
    BEHAVIORAL_BACKFILL_MERGE_GATE_ATTESTED=True,
    BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_SIZING_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TTL_ATTESTED=True,
    BEHAVIORAL_BACKFILL_PERSON_TOPIC_BYTES_BUDGET=1_000_000,
    BEHAVIORAL_BACKFILL_MAX_SCAN_EVENTS_PER_DAY=1_000,
)
class TestRealtimeCohortRequests(BaseTest):
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

    def _request(self, request_id: Any) -> RealtimeCohortRequest:
        return RealtimeCohortRequest.objects.for_team(self.team.id).get(id=request_id)

    def _submit_and_run(self, submit: Callable[[], RealtimeCohortRequest]) -> RealtimeCohortRequest:
        with self.captureOnCommitCallbacks() as callbacks:
            request = submit()
        # Run the queued task alone. `execute=True` would also run the cohort save hooks that `enable` queues.
        [queue_task] = callbacks
        queue_task()
        return self._request(request.id)

    def _enable(self) -> RealtimeCohortRequest:
        return self._submit_and_run(
            lambda: submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")
        )

    def _behavioral_backfill(self, *, skip_scan_limit: bool) -> RealtimeCohortRequest:
        return submit_backfill(
            self.team.id,
            backfill_kind=CohortBackfillKind.BEHAVIORAL,
            cohort_ids=None,
            skip_scan_limit=skip_scan_limit,
            requested_by_id=self.user.id,
        )

    def _level(self) -> str:
        return RealtimeCohortTeamAccess.objects.get(team=self.team).level

    def test_an_enable_refused_over_the_scan_limit_is_done_after_a_backfill_that_skips_the_limit(self) -> None:
        self._cohort(PERSON_LEAF, PAGEVIEW_LEAF)
        self.peak_day_events = 2_000

        refused = self._enable()

        assert refused.state == RealtimeCohortRequestState.REFUSED
        assert refused.error.startswith("Behavioral run refused: The run would scan 2000 events on its busiest day")
        assert refused.detail.splitlines()[0] == f"Team {self.team.id}: processing"
        assert self._level() == RealtimeCohortLevel.PROCESSING

        backfill = self._submit_and_run(lambda: self._behavioral_backfill(skip_scan_limit=True))

        [behavioral_run] = CohortBackfillRun.objects.for_team(self.team.id).filter(
            backfill_kind=CohortBackfillKind.BEHAVIORAL
        )
        assert (backfill.state, backfill.detail, behavioral_run.created_by_id) == (
            RealtimeCohortRequestState.DONE,
            f"Created run {behavioral_run.id}",
            self.user.id,
        )

        enabled = self._enable()

        assert (enabled.state, enabled.error) == (RealtimeCohortRequestState.DONE, "")
        assert self._level() == RealtimeCohortLevel.SERVING

    def test_a_second_delivery_of_a_claimed_request_changes_nothing(self) -> None:
        self._cohort(PERSON_LEAF, PAGEVIEW_LEAF)
        request = submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")
        RealtimeCohortRequest.objects.for_team(self.team.id).filter(id=request.id).update(
            state=RealtimeCohortRequestState.RUNNING
        )

        process_request(self.team.id, request.id)

        assert self._request(request.id).state == RealtimeCohortRequestState.RUNNING
        assert not RealtimeCohortTeamAccess.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("queued", None, RealtimeCohortRequestState.FAILED),
            ("running_since_the_submit", timedelta(0), RealtimeCohortRequestState.FAILED),
            # A worker that claims the request after it waited out the limit in the queue still owns it.
            ("running_since_it_waited_in_the_queue", REQUEST_STALE_AFTER, RealtimeCohortRequestState.RUNNING),
        ]
    )
    def test_a_submit_replaces_an_unfinished_request_only_once_it_is_stale(
        self, _name: str, started_after: timedelta | None, state_after_a_later_submit: RealtimeCohortRequestState
    ) -> None:
        with time_machine.travel(SUBMITTED_AT, tick=False):
            unfinished = submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")
            with self.assertRaisesMessage(ValueError, "This team already has a request in progress"):
                submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")
        if started_after is not None:
            RealtimeCohortRequest.objects.for_team(self.team.id).filter(id=unfinished.id).update(
                state=RealtimeCohortRequestState.RUNNING, started_at=SUBMITTED_AT + started_after
            )

        later = time_machine.travel(SUBMITTED_AT + REQUEST_STALE_AFTER + timedelta(minutes=1), tick=False)
        if state_after_a_later_submit == RealtimeCohortRequestState.FAILED:
            with later:
                submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")
        else:
            with later, self.assertRaisesMessage(ValueError, "This team already has a request in progress"):
                submit_enablement(self.team.id, requested_by_id=self.user.id, reason="Beta signup")

        assert self._request(unfinished.id).state == state_after_a_later_submit

    def test_a_behavioral_backfill_without_its_attestations_is_refused_and_creates_no_run(self) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team, level=RealtimeCohortLevel.PROCESSING, purpose=RealtimeCohortAccessPurpose.BETA
        )
        Cohort.objects.create(team=self.team, filters={"properties": {"type": "AND", "values": [PAGEVIEW_LEAF]}})
        with self.captureOnCommitCallbacks() as callbacks:
            queued = self._behavioral_backfill(skip_scan_limit=True)

        with override_settings(BEHAVIORAL_BACKFILL_DURABILITY_ATTESTED=False):
            [queue_task] = callbacks
            queue_task()
            with self.assertRaisesMessage(ValueError, "Missing operator attestations: processor durability"):
                self._behavioral_backfill(skip_scan_limit=True)

        refused = self._request(queued.id)
        assert (refused.state, refused.error) == (
            RealtimeCohortRequestState.REFUSED,
            "Missing operator attestations: processor durability",
        )
        assert RealtimeCohortRequest.objects.for_team(self.team.id).count() == 1
        assert not CohortBackfillRun.objects.for_team(self.team.id).exists()

    def test_an_unexpected_error_fails_the_request(self) -> None:
        RealtimeCohortTeamAccess.objects.create(
            team=self.team, level=RealtimeCohortLevel.PROCESSING, purpose=RealtimeCohortAccessPurpose.BETA
        )
        Cohort.objects.create(team=self.team, filters={"properties": {"type": "AND", "values": [PAGEVIEW_LEAF]}})

        with mock.patch(
            "products.cohorts.backend.realtime_enablement.estimate_behavioral_scan_events",
            side_effect=RuntimeError("ClickHouse timeout"),
        ):
            failed = self._submit_and_run(lambda: self._behavioral_backfill(skip_scan_limit=False))

        assert (failed.state, failed.error) == (RealtimeCohortRequestState.FAILED, "ClickHouse timeout")
