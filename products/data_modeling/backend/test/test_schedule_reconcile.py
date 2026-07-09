from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from temporalio.client import ScheduleAlreadyRunningError, ScheduleListActionStartWorkflow

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.schedule_reconcile import maybe_reconcile_dag, reconcile_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import NodeType
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW
from products.data_modeling.backend.test.helpers import (
    saved_query_node as _saved_query_node,
    table_node as _table_node,
    warehouse_source_node as _warehouse_source_node,
)

RECONCILE = "products.data_modeling.backend.logic.schedule_reconcile"

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)


def _listing(schedule_id, workflow="data-modeling-execute-dag"):
    action = mock.Mock(spec=ScheduleListActionStartWorkflow, workflow=workflow)
    return mock.Mock(id=schedule_id, schedule=mock.Mock(action=action))


@pytest.mark.django_db
class TestReconcileDagSchedules(BaseTest):
    def test_creates_tier_scoped_schedule_and_deletes_stale_one(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        dag_id = str(dag.id)
        stale_id = tier_schedule_id(dag_id, H1)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(stale_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        # one 15min tier created, scoped to exactly the two schedulable nodes
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(dag_id, M15))
        created_inputs = create.call_args.kwargs["schedule"].action.args[0]
        self.assertEqual(sorted(created_inputs["node_ids"]), sorted([str(matview.id), str(endpoint.id)]))

        # tagged with the schedule type: get_v2_scheduled_dag_ids' unscoped sweep filters on it,
        # so an untagged tier schedule would make its DAG look un-migrated
        created_attrs = {pair.key.name: pair.value for pair in create.call_args.kwargs["search_attributes"]}
        self.assertEqual(created_attrs[POSTHOG_SCHEDULE_TYPE_KEY.name], DATA_MODELING_EXECUTE_DAG_WORKFLOW)

        # the stale H1 schedule is removed; nothing to update
        update.assert_not_called()
        delete.assert_called_once_with(temporal, schedule_id=stale_id)

    def test_rewrites_persisting_tier_without_create_or_delete(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        Edge.objects.create(team=self.team, dag=dag, source=matview, target=endpoint)
        set_declared_target(endpoint, M15)

        dag_id = str(dag.id)
        existing_id = tier_schedule_id(dag_id, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(existing_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        # the 15min tier already exists, so it is rewritten in place — no create, no delete
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], existing_id)
        create.assert_not_called()
        delete.assert_not_called()

    def test_rolls_back_created_tiers_and_keeps_legacy_schedule_on_failure(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        ep_fast = _saved_query_node(self.team, dag, "fast", NodeType.ENDPOINT)
        ep_slow = _saved_query_node(self.team, dag, "slow", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=ep_fast)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=ep_slow)
        set_declared_target(ep_fast, M15)
        set_declared_target(ep_slow, H6)

        legacy_id = str(dag.id)  # migration-era single schedule, slated for deletion once tiers exist

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(legacy_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        created_ids: list[str] = []

        async def failing_create(*_args, **kwargs):
            created_ids.append(kwargs["id"])
            if len(created_ids) >= 2:  # second tier creation fails partway through the migration
                raise RuntimeError("temporal unavailable")

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock(side_effect=failing_create)),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()),
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.assertRaises(RuntimeError):
                reconcile_dag_schedules(dag)

        # the one successfully-created tier is rolled back; the legacy schedule is never deleted,
        # so the DAG stays fully covered at its current cadence rather than opening a gap
        delete.assert_called_once_with(temporal, schedule_id=created_ids[0])
        self.assertNotEqual(created_ids[0], legacy_id)

    def test_refuses_to_unschedule_covered_dag_without_targets(self):
        # a covered DAG with no targets means unseeded conversion, not a wind-down —
        # converging to zero schedules would silently stop all materialization
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)

        legacy_id = str(dag.id)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                yield _listing(legacy_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        create.assert_not_called()
        delete.assert_not_called()

    def test_concurrent_create_converges_to_update_without_rollback(self):
        # a concurrent reconcile already created the tier; the loser must converge onto it,
        # not roll it back — rolling back would delete the winner's live schedule
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(
                f"{RECONCILE}.a_create_schedule",
                new=mock.AsyncMock(side_effect=ScheduleAlreadyRunningError()),
            ),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            reconcile_dag_schedules(dag)

        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], tier_schedule_id(str(dag.id), M15))
        delete.assert_not_called()

    def test_refuses_non_bucket_tier_before_touching_temporal(self):
        # the guard must fire before any Temporal call — a non-bucket tier would crash
        # build_schedule_spec mid-apply and leave the DAG partially reconciled
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, timedelta(minutes=45))

        with mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock()) as connect:
            with self.assertRaises(UnsupportedFrequencyTargetError):
                reconcile_dag_schedules(dag)
        connect.assert_not_called()

    def test_clamps_a_target_finer_than_its_source_can_deliver(self):
        # a matview target drifted below its source floor (e.g. the import later slowed to 6h):
        # reconcile must schedule it at the source floor, not the wasteful finer cadence
        dag = DAG.get_or_create_default(self.team)
        source = _warehouse_source_node(self.team, dag, sync_frequency_interval=H6)
        matview = _saved_query_node(self.team, dag, "mv", NodeType.MAT_VIEW)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=matview)
        set_declared_target(matview, M15)

        dag_id = str(dag.id)

        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                return
                yield  # pragma: no cover — empty async generator

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules

        with (
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
        ):
            reconcile_dag_schedules(dag)

        # clamped to the 6h source floor, not the declared 15min
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(dag_id, H6))


@pytest.mark.django_db
class TestMaybeReconcileDag(BaseTest):
    def _dag_with_target(self):
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, M15)
        return dag

    def _temporal_listing(self, schedule_ids):
        async def fake_list_schedules(*_args, **_kwargs):
            async def gen():
                for schedule_id in schedule_ids:
                    yield _listing(schedule_id)

            return gen()

        temporal = mock.Mock()
        temporal.list_schedules = fake_list_schedules
        return temporal

    def test_flag_off_never_touches_temporal(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=False),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock()) as connect,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        connect.assert_not_called()

    def test_untiered_dag_is_left_alone(self):
        # a legacy single-schedule DAG converts only via the conversion command; a mutation
        # trigger must neither unschedule it nor create tiers next to live v1 schedules
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(
                f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([str(dag.id)]))
            ),
            mock.patch(f"{RECONCILE}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        create.assert_not_called()
        update.assert_not_called()
        delete.assert_not_called()

    def test_tiered_dag_reconciles_after_commit(self):
        dag = self._dag_with_target()
        tier_id = tier_schedule_id(str(dag.id), M15)
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(
                f"{RECONCILE}.async_connect", new=mock.AsyncMock(return_value=self._temporal_listing([tier_id]))
            ),
            mock.patch(f"{RECONCILE}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{RECONCILE}.a_delete_schedule", new=mock.AsyncMock()),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        update.assert_called_once()
        self.assertEqual(update.call_args.kwargs["id"], tier_id)

    def test_reconcile_failure_never_raises_past_commit(self):
        dag = self._dag_with_target()
        with (
            mock.patch(f"{RECONCILE}.feature_enabled_or_false", return_value=True),
            mock.patch(f"{RECONCILE}.async_connect", new=mock.AsyncMock(side_effect=RuntimeError("temporal down"))),
            mock.patch(f"{RECONCILE}.capture_exception") as capture,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                maybe_reconcile_dag(dag)
        capture.assert_called_once()
