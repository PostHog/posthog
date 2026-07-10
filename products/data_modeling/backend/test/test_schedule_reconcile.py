from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from temporalio.client import ScheduleListActionStartWorkflow

from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_TYPE_KEY

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import UnsupportedFrequencyTargetError
from products.data_modeling.backend.logic.node_frequency import set_declared_target
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType
from products.data_modeling.backend.schedule import DATA_MODELING_EXECUTE_DAG_WORKFLOW
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)
H6 = timedelta(hours=6)


def _table_node(team, dag, name, properties):
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def _saved_query_node(team, dag, name, node_type):
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


def _warehouse_source_node(team, dag, *, sync_frequency_interval):
    table = DataWarehouseTable.objects.create(name="stripe_charges", team=team)
    source = ExternalDataSource.objects.create(
        team=team,
        source_id="source_id",
        connection_id="connection_id",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.STRIPE,
        prefix="posthog_test_",
    )
    ExternalDataSchema.objects.create(
        name="stripe_charges",
        team=team,
        source=source,
        table=table,
        sync_frequency_interval=sync_frequency_interval,
        should_sync=True,
    )
    return _table_node(team, dag, "stripe_charges", {"origin": "warehouse", "warehouse_table_id": str(table.id)})


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

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{module}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
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

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
            mock.patch(f"{module}.a_update_schedule", new=mock.AsyncMock()) as update,
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
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

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock(side_effect=failing_create)),
            mock.patch(f"{module}.a_update_schedule", new=mock.AsyncMock()),
            mock.patch(f"{module}.a_delete_schedule", new=mock.AsyncMock()) as delete,
        ):
            with self.assertRaises(RuntimeError):
                reconcile_dag_schedules(dag)

        # the one successfully-created tier is rolled back; the legacy schedule is never deleted,
        # so the DAG stays fully covered at its current cadence rather than opening a gap
        delete.assert_called_once_with(temporal, schedule_id=created_ids[0])
        self.assertNotEqual(created_ids[0], legacy_id)

    def test_refuses_non_bucket_tier_before_touching_temporal(self):
        # the guard must fire before any Temporal call — a non-bucket tier would crash
        # build_schedule_spec mid-apply and leave the DAG partially reconciled
        dag = DAG.get_or_create_default(self.team)
        source = _table_node(self.team, dag, "events", {"origin": "posthog"})
        endpoint = _saved_query_node(self.team, dag, "ep", NodeType.ENDPOINT)
        Edge.objects.create(team=self.team, dag=dag, source=source, target=endpoint)
        set_declared_target(endpoint, timedelta(minutes=45))

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        with mock.patch(f"{module}.async_connect", new=mock.AsyncMock()) as connect:
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

        module = "products.data_modeling.backend.logic.schedule_reconcile"
        with (
            mock.patch(f"{module}.async_connect", new=mock.AsyncMock(return_value=temporal)),
            mock.patch(f"{module}.a_create_schedule", new=mock.AsyncMock()) as create,
        ):
            reconcile_dag_schedules(dag)

        # clamped to the 6h source floor, not the declared 15min
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["id"], tier_schedule_id(dag_id, H6))
