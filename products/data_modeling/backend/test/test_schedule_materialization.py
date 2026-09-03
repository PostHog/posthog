from datetime import timedelta

from posthog.test.base import BaseTest
from unittest import mock

from products.data_modeling.backend.logic.cohort_scheduling import is_tier_schedule_id
from products.data_modeling.backend.logic.freshness import UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import get_declared_target, set_declared_target
from products.data_modeling.backend.models import DAG, Node
from products.data_modeling.backend.models.datawarehouse_saved_query import (
    DataWarehouseSavedQuery,
    V1SchedulingPathReached,
)
from products.data_modeling.backend.models.node import NodeType

MODEL = "products.data_modeling.backend.models.datawarehouse_saved_query"
GET_V2_DAG_IDS = "products.data_modeling.backend.schedule.get_v2_scheduled_dag_ids"
RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"
NODE_MAT = "products.data_modeling.backend.logic.node_materialization"


def _no_schedules():
    """A Temporal client whose schedule listing is empty — a DAG nothing has ever scheduled."""

    async def list_schedules(*_args, **_kwargs):
        async def gen():
            return
            yield  # pragma: no cover - makes gen an async generator

        return gen()

    temporal = mock.Mock()
    temporal.list_schedules = list_schedules
    return temporal


class TestScheduleMaterializationV2Guard(BaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="Default")
        self.sq = DataWarehouseSavedQuery.objects.create(
            name="view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=12),
        )
        Node.objects.create(team=self.team, dag=self.dag, saved_query=self.sq, type=NodeType.VIEW)

    def test_skips_v1_and_nulls_frequency_when_dag_on_v2(self):
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch.object(DataWarehouseSavedQuery, "setup_model_paths") as setup_paths,
            mock.patch(f"{NODE_MAT}.sync_connect") as sync_connect,
            mock.patch(f"{MODEL}.capture_exception") as capture,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.sq.schedule_materialization()
        setup_paths.assert_not_called()
        # reporting on the healthy path would bury the one signal that matters
        capture.assert_not_called()
        # a frequency-only call carries no enable intent, so it must not start a one-off run
        sync_connect.assert_not_called()
        self.sq.refresh_from_db()
        assert self.sq.sync_frequency_interval is None

    def test_saved_query_whose_node_vanished_is_refused_instead_of_scheduled(self):
        nodeless = DataWarehouseSavedQuery.objects.create(
            name="sync_failed",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
            sync_frequency_interval=timedelta(hours=12),
            is_materialized=True,
        )
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            self.captureOnCommitCallbacks(execute=True),
        ):
            nodeless.schedule_materialization()
        nodeless.refresh_from_db()
        assert nodeless.is_materialized is False

    def test_disables_materialization_when_dag_is_not_on_v2(self):
        self.sq.is_materialized = True
        self.sq.save(update_fields=["is_materialized"])
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{RECONCILE}.schedule_exists", return_value=True),
            mock.patch(f"{MODEL}.capture_exception") as capture,
        ):
            self.sq.schedule_materialization()

        self.sq.refresh_from_db()
        assert self.sq.is_materialized is False
        assert isinstance(capture.call_args.args[0], V1SchedulingPathReached)
        assert capture.call_args.args[1]["team_id"] == self.team.pk

    def test_virgin_dag_is_born_on_tiers_instead_of_minting_a_v1_schedule(self):
        # a brand-new team's DAG has no v2 schedule *and* no v1 schedules, so the v2 lookup says
        # "not on v2" and the query would get a per-query v1 schedule — that is how every new team
        # lands on v1 and why the v1 population grows on its own
        node = Node.objects.get(saved_query=self.sq)
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{RECONCILE}.schedule_exists", return_value=False),
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_no_schedules())),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{NODE_MAT}.sync_connect"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.sq.schedule_materialization()

        create.assert_called_once()
        assert is_tier_schedule_id(create.call_args.kwargs["id"])
        node.refresh_from_db()
        assert get_declared_target(node) == timedelta(hours=12)
        self.sq.refresh_from_db()
        assert self.sq.sync_frequency_interval is None

    def test_virgin_dag_is_born_on_tiers_with_the_tiered_flag_off(self):
        # nothing mints v1 schedules any more, so a bootstrap the flag declines leaves the query
        # with no scheduler at all — and the flag reads false on every self-hosted deployment
        node = Node.objects.get(saved_query=self.sq)
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{RECONCILE}.schedule_exists", return_value=False),
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=False),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_no_schedules())),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{NODE_MAT}.sync_connect"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.sq.schedule_materialization()

        create.assert_called_once()
        assert is_tier_schedule_id(create.call_args.kwargs["id"])
        # the flag gates the write-through path, so the requested cadence has to survive as a
        # seeded target instead
        node.refresh_from_db()
        assert get_declared_target(node) == timedelta(hours=12)

    def test_failed_bootstrap_retracts_the_materialized_claim(self):
        # the reconcile runs after the caller's transaction commits, so a failure has no caller
        # left to raise into: leaving is_materialized set would report a schedule that was
        # never created
        self.sq.is_materialized = True
        self.sq.save(update_fields=["is_materialized"])
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{RECONCILE}.schedule_exists", return_value=False),
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_no_schedules())),
            mock.patch(
                f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock(side_effect=Exception("temporal unavailable"))
            ),
            mock.patch(f"{RECONCILE}.capture_exception"),
            mock.patch(f"{NODE_MAT}.sync_connect"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.sq.schedule_materialization()

        self.sq.refresh_from_db()
        assert self.sq.is_materialized is False

    def test_rejected_frequency_leaves_a_virgin_dag_unbootstrapped(self):
        # the bootstrap is all side effects, and on_commit fires immediately for the callers that
        # are not inside an atomic block — so seeding or scheduling before the frequency is
        # validated converts the DAG to v2 on a request that then 400s
        node = Node.objects.get(saved_query=self.sq)
        self.sq.sync_frequency_interval = timedelta(minutes=45)
        self.sq.save(update_fields=["sync_frequency_interval"])
        with (
            mock.patch(GET_V2_DAG_IDS, return_value=set()),
            mock.patch(f"{RECONCILE}.schedule_exists", return_value=False),
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(f"{RECONCILE}.sync_connect"),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=_no_schedules())),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            self.captureOnCommitCallbacks(execute=True),
            self.assertRaises(UnsupportedFrequencyTargetError),
        ):
            self.sq.schedule_materialization()

        create.assert_not_called()
        node.refresh_from_db()
        assert get_declared_target(node) is None

    def test_tiered_flag_writes_target_through_and_nulls_interval(self):
        node = Node.objects.get(saved_query=self.sq)
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{RECONCILE}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag") as reconcile,
        ):
            self.sq.schedule_materialization()
        node.refresh_from_db()
        self.sq.refresh_from_db()
        assert get_declared_target(node) == timedelta(hours=12)
        assert self.sq.sync_frequency_interval is None
        reconcile.assert_called_once()

    def test_tiered_call_without_interval_keeps_existing_target(self):
        # a caller with no frequency opinion (e.g. re-enabling materialization) must not
        # wipe the node target — the interval is transport, not state
        node = Node.objects.get(saved_query=self.sq)
        set_declared_target(node, timedelta(hours=6))
        self.sq.sync_frequency_interval = None
        self.sq.save(update_fields=["sync_frequency_interval"])
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{RECONCILE}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
        ):
            self.sq.schedule_materialization()
        node.refresh_from_db()
        assert get_declared_target(node) == timedelta(hours=6)

    def test_revert_materialization_on_tiered_clears_target(self):
        # without this a reverted matview stays in its cadence tier and keeps materializing
        node = Node.objects.get(saved_query=self.sq)
        set_declared_target(node, timedelta(hours=12))
        with (
            mock.patch(f"{RECONCILE}.tiered_schedules_enabled", return_value=True),
            mock.patch(f"{RECONCILE}.maybe_reconcile_dag"),
            mock.patch("products.data_warehouse.backend.facade.api.delete_saved_query_schedule"),
        ):
            self.sq.revert_materialization()
        node.refresh_from_db()
        assert get_declared_target(node) is None

    def test_tiered_flag_surfaces_invalid_frequency_without_disabling(self):
        # an invalid frequency is a request problem: it must reach the caller as a validation
        # error, not silently flip is_materialized like infrastructure failures do
        self.sq.is_materialized = True
        self.sq.sync_frequency_interval = timedelta(minutes=45)
        self.sq.save(update_fields=["is_materialized", "sync_frequency_interval"])
        with (
            mock.patch(GET_V2_DAG_IDS, return_value={str(self.dag.id)}),
            mock.patch(f"{RECONCILE}.tiered_schedules_enabled", return_value=True),
        ):
            try:
                self.sq.schedule_materialization()
                raise AssertionError("expected UnsupportedFrequencyTargetError")
            except UnsupportedFrequencyTargetError:
                pass
        self.sq.refresh_from_db()
        assert self.sq.is_materialized is True
        # validation raises before the interval is nulled — the rejected write stays
        # visible for retry
        assert self.sq.sync_frequency_interval == timedelta(minutes=45)

    def test_disables_materialization_when_v2_lookup_fails(self):
        self.sq.is_materialized = True
        self.sq.save(update_fields=["is_materialized"])
        with mock.patch(GET_V2_DAG_IDS, side_effect=Exception("temporal unavailable")):
            self.sq.schedule_materialization()
        self.sq.refresh_from_db()
        assert self.sq.is_materialized is False
