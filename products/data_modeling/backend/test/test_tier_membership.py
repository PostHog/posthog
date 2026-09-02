import asyncio
from datetime import timedelta

from unittest import mock

from parameterized import parameterized
from temporalio.client import ScheduleActionStartWorkflow, ScheduleListActionStartWorkflow

from products.data_modeling.backend.logic.cohort_scheduling import Tier
from products.data_modeling.backend.logic.tier_membership import (
    CORRECTLY_UNSCHEDULED,
    OVER_SCHEDULED,
    SCHEDULED,
    SCHEDULED_WRONG_TIER,
    STALE_NEEDS_RECONCILE,
    UNSUPPORTED_TARGET,
    LiveTier,
    classify_node,
    read_live_tiers,
)

DAILY = Tier(timedelta(days=1))
DAILY_ANCHORED = Tier(timedelta(days=1), 1350)


def _tier(interval_seconds, node_ids, anchor_minutes=None):
    schedule_id = "dag" if interval_seconds is None else f"dag:{interval_seconds}"
    if anchor_minutes is not None:
        schedule_id += f":{anchor_minutes}"
    return LiveTier(
        schedule_id=schedule_id,
        interval_seconds=interval_seconds,
        covers_whole_dag=node_ids is None,
        node_ids=frozenset(node_ids) if node_ids is not None else None,
        anchor_minutes=anchor_minutes,
    )


class TestClassifyNode:
    @parameterized.expand(
        [
            # (live_tiers, expected_tier, expected_verdict)
            ("on the tier it should be on", [_tier(86400, {"n"})], DAILY, SCHEDULED),
            ("covered by a whole-DAG schedule", [_tier(None, None)], DAILY, SCHEDULED),
            ("scheduled but at the wrong cadence", [_tier(3600, {"n"})], DAILY, SCHEDULED_WRONG_TIER),
            # The managed_product_lifecycle case: has a target, but no live tier lists it.
            ("has a target but no live tier covers it", [_tier(86400, {"other"})], DAILY, STALE_NEEDS_RECONCILE),
            ("no tiers exist at all yet", [], DAILY, STALE_NEEDS_RECONCILE),
            ("in a tier reconcile would drop", [_tier(86400, {"n"})], None, OVER_SCHEDULED),
            ("no target and no tier — the opt-out", [_tier(86400, {"other"})], None, CORRECTLY_UNSCHEDULED),
            # anchor drift is drift: a live hash-spread schedule does not satisfy an anchored
            # expectation (or vice versa), else the exact state anchors are set to escape
            # reads as healthy
            ("anchored expectation, unanchored live tier", [_tier(86400, {"n"})], DAILY_ANCHORED, SCHEDULED_WRONG_TIER),
            ("anchored expectation matched", [_tier(86400, {"n"}, 1350)], DAILY_ANCHORED, SCHEDULED),
            ("unanchored expectation, anchored live tier", [_tier(86400, {"n"}, 1350)], DAILY, SCHEDULED_WRONG_TIER),
        ]
    )
    def test_verdict(self, _name, live_tiers, expected_tier, expected_verdict):
        status = classify_node(
            node_id="n",
            name="a_view",
            node_type="matview",
            dag_id="dag",
            dag_name="Default",
            live_tiers=live_tiers,
            expected_tier=expected_tier,
        )
        assert status.verdict == expected_verdict

    def test_blocked_dag_does_not_advise_a_reconcile_that_would_refuse(self):
        # reconcile raises UnsupportedFrequencyTargetError for the WHOLE DAG when a desired tier is
        # not a schedulable bucket, touching no schedule. Reporting stale_needs_reconcile there sends
        # an operator to run a reconcile that fixes nothing and takes the rest of the DAG with it.
        status = classify_node(
            node_id="n",
            name="a_view",
            node_type="matview",
            dag_id="dag",
            dag_name="Default",
            live_tiers=[],
            expected_tier=DAILY,
            reconcile_blocked=True,
        )
        assert status.verdict == UNSUPPORTED_TARGET
        assert status.dag_reconcile_blocked is True


class TestReadLiveTiers:
    def _listing(self, schedule_id, workflow):
        action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow=workflow)
        return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))

    def _describe_returning(self, node_ids):
        # node_ids=None models a whole-DAG schedule (the arg dict has no node_ids key).
        payload = {"team_id": 2, "dag_id": "dag"} if node_ids is None else {"team_id": 2, "node_ids": node_ids}
        action = mock.Mock(spec=ScheduleActionStartWorkflow, args=[payload])
        described = mock.Mock(schedule=mock.Mock(action=action))
        return mock.AsyncMock(return_value=described)

    def test_reads_node_ids_and_ignores_non_execute_dag(self):
        listings = [
            self._listing("dag:86400", "data-modeling-execute-dag"),
            self._listing("dag:86400:1350", "data-modeling-execute-dag"),  # anchored cohort
            self._listing("dag", "data-modeling-execute-dag"),  # legacy single schedule (whole DAG)
            self._listing("some-sq-id", "data-modeling-run"),  # v1 — must be ignored
        ]
        describe_by_id = {
            "dag:86400": self._describe_returning(["n1", "n2"]),
            "dag:86400:1350": self._describe_returning(["n3"]),
            "dag": self._describe_returning(None),
        }

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                for listing in listings:
                    yield listing

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        temporal.get_schedule_handle = lambda sid: mock.Mock(describe=describe_by_id[sid])

        tiers = asyncio.run(read_live_tiers(temporal, "dag"))

        by_id = {t.schedule_id: t for t in tiers}
        # the v1 data-modeling-run schedule was skipped
        assert set(by_id) == {"dag:86400", "dag:86400:1350", "dag"}
        assert by_id["dag:86400"].node_ids == frozenset({"n1", "n2"})
        assert (by_id["dag:86400"].covers_whole_dag, by_id["dag:86400"].anchor_minutes) == (False, None)
        assert (by_id["dag:86400:1350"].interval_seconds, by_id["dag:86400:1350"].anchor_minutes) == (86400, 1350)
        assert by_id["dag:86400:1350"].node_ids == frozenset({"n3"})
        assert by_id["dag"].covers_whole_dag is True
        assert by_id["dag"].node_ids is None
