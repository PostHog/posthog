from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import mock

from temporalio.client import ScheduleListActionStartWorkflow

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.node_frequency import set_frequency_target
from products.data_modeling.backend.logic.schedule_reconcile import reconcile_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

M15 = timedelta(minutes=15)
H1 = timedelta(hours=1)


def _table_node(team, dag, name, properties):
    return Node.objects.create(team=team, dag=dag, name=name, type=NodeType.TABLE, properties=properties)


def _saved_query_node(team, dag, name, node_type):
    saved_query = DataWarehouseSavedQuery.objects.create(
        name=name, team=team, query={"query": "SELECT 1", "kind": "HogQLQuery"}
    )
    return Node.objects.create(team=team, dag=dag, saved_query=saved_query, type=node_type)


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
        set_frequency_target(endpoint, M15)

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

        # the stale H1 schedule is removed; nothing to update
        update.assert_not_called()
        delete.assert_called_once_with(temporal, schedule_id=stale_id)
