from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest import TestCase, mock

from parameterized import parameterized
from temporalio.client import ScheduleListActionStartWorkflow

from products.data_modeling.backend.logic.cohort_scheduling import tier_schedule_id
from products.data_modeling.backend.logic.freshness import STREAMING
from products.data_modeling.backend.logic.node_frequency import FrequencyGraph, set_frequency_target
from products.data_modeling.backend.logic.schedule_reconcile import _find_unsatisfiable, reconcile_dag_schedules
from products.data_modeling.backend.models.dag import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.edge import Edge
from products.data_modeling.backend.models.node import Node, NodeType

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


class TestFindUnsatisfiable(TestCase):
    @parameterized.expand(
        [
            # scheduled finer than the 6h source delivers -> flagged
            ("finer_than_source_floor", M15, H6, True),
            # exactly at the floor -> satisfiable
            ("at_floor", H6, H6, False),
            # coarser than the floor -> satisfiable
            ("coarser_than_floor", H6, H1, False),
            # streamed source imposes no floor -> satisfiable at any cadence
            ("streamed_source", M15, STREAMING, False),
        ]
    )
    def test_flags_node_finer_than_its_source(self, _name, effective, source_interval, flagged):
        graph = FrequencyGraph(
            nodes={"a"},
            edges=[("src", "a")],
            targets={"a": effective},
            source_intervals={"src": source_interval},
            best_effort_source_ids=set(),
        )
        result = _find_unsatisfiable(graph, {"a": effective}, {"a": effective})
        if flagged:
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].node_id, "a")
            self.assertEqual(result[0].floor, source_interval)
        else:
            self.assertEqual(result, [])

    def test_unscheduled_node_is_never_flagged(self):
        graph = FrequencyGraph(
            nodes={"a"}, edges=[("src", "a")], targets={}, source_intervals={"src": H6}, best_effort_source_ids=set()
        )
        self.assertEqual(_find_unsatisfiable(graph, {"a": None}, {}), [])
