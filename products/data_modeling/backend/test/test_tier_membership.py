import asyncio

from unittest import mock

from parameterized import parameterized
from temporalio.client import ScheduleActionStartWorkflow, ScheduleListActionStartWorkflow

from products.data_modeling.backend.logic.tier_membership import (
    CORRECTLY_UNSCHEDULED,
    OVER_SCHEDULED,
    SCHEDULED,
    SCHEDULED_WRONG_TIER,
    STALE_NEEDS_RECONCILE,
    LiveTier,
    classify_node,
    read_live_tiers,
)


def _tier(interval_seconds, node_ids):
    return LiveTier(
        schedule_id=f"dag:{interval_seconds}" if interval_seconds is not None else "dag",
        interval_seconds=interval_seconds,
        covers_whole_dag=node_ids is None,
        node_ids=frozenset(node_ids) if node_ids is not None else None,
    )


class TestClassifyNode:
    @parameterized.expand(
        [
            # (live_tiers, expected_interval, expected_verdict)
            ("on the tier it should be on", [_tier(86400, {"n"})], 86400, SCHEDULED),
            ("covered by a whole-DAG schedule", [_tier(None, None)], 86400, SCHEDULED),
            ("scheduled but at the wrong cadence", [_tier(3600, {"n"})], 86400, SCHEDULED_WRONG_TIER),
            # The managed_product_lifecycle case: has a target, but no live tier lists it.
            ("has a target but no live tier covers it", [_tier(86400, {"other"})], 86400, STALE_NEEDS_RECONCILE),
            ("no tiers exist at all yet", [], 86400, STALE_NEEDS_RECONCILE),
            ("in a tier reconcile would drop", [_tier(86400, {"n"})], None, OVER_SCHEDULED),
            ("no target and no tier — the opt-out", [_tier(86400, {"other"})], None, CORRECTLY_UNSCHEDULED),
        ]
    )
    def test_verdict(self, _name, live_tiers, expected_interval, expected_verdict):
        status = classify_node(
            node_id="n",
            name="a_view",
            node_type="matview",
            dag_id="dag",
            dag_name="Default",
            live_tiers=live_tiers,
            expected_interval=expected_interval,
        )
        assert status.verdict == expected_verdict


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
            self._listing("dag", "data-modeling-execute-dag"),  # legacy single schedule (whole DAG)
            self._listing("some-sq-id", "data-modeling-run"),  # v1 — must be ignored
        ]
        describe_by_id = {
            "dag:86400": self._describe_returning(["n1", "n2"]),
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

        by_interval = {t.interval_seconds: t for t in tiers}
        assert set(by_interval) == {86400, None}  # the v1 data-modeling-run schedule was skipped
        assert by_interval[86400].node_ids == frozenset({"n1", "n2"})
        assert by_interval[86400].covers_whole_dag is False
        assert by_interval[None].covers_whole_dag is True
        assert by_interval[None].node_ids is None
