from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.models import DAG, Edge, Node
from products.data_modeling.backend.models.edge import DAGMismatchError
from products.data_warehouse.backend.models import DataWarehouseSavedQuery

A_DAG_ID = "A"
B_DAG_ID = "B"


def _basic_saved_query_with_label(label: str):
    return f"""SELECT '{label}'"""


class DagMismatchTest(BaseTest):
    dag_a: DAG
    dag_b: DAG

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with freeze_time("2025-01-01T12:00:00.000Z"):
            cls.dag_a = DAG.objects.create(team=cls.team, name=A_DAG_ID)
            cls.dag_b = DAG.objects.create(team=cls.team, name=B_DAG_ID)
            a1_query = DataWarehouseSavedQuery.objects.create(
                name="a1",
                team=cls.team,
                query=_basic_saved_query_with_label("a1"),
            )
            a2_query = DataWarehouseSavedQuery.objects.create(
                name="a2",
                team=cls.team,
                query=_basic_saved_query_with_label("a2"),
            )
            a3_query = DataWarehouseSavedQuery.objects.create(
                name="a3",
                team=cls.team,
                query=_basic_saved_query_with_label("a3"),
            )
            a1_node = Node.objects.create(team=cls.team, dag=cls.dag_a, saved_query=a1_query, name="a1")
            a2_node = Node.objects.create(team=cls.team, dag=cls.dag_a, saved_query=a2_query, name="a2")
            # a3 intentionally left disconnected to test connecting two nodes with same dag id with an edge
            # that has a different dag
            Node.objects.create(team=cls.team, dag=cls.dag_a, saved_query=a3_query, name="a3")
            Edge.objects.create(team=cls.team, dag=cls.dag_a, source=a1_node, target=a2_node)
            b_query = DataWarehouseSavedQuery.objects.create(
                name="b",
                team=cls.team,
                query=_basic_saved_query_with_label("b"),
            )
            Node.objects.create(team=cls.team, dag=cls.dag_b, saved_query=b_query, name="b")

    @parameterized.expand(
        [
            # create edge from A to B DAG should fail regardless of dag id
            ("a1", "b", A_DAG_ID),
            ("a2", "b", A_DAG_ID),
            ("a1", "b", B_DAG_ID),
            ("a2", "b", B_DAG_ID),
            # create edge from A to A DAG should fail if edge belongs to DAG B
            ("a1", "a3", B_DAG_ID),
        ],
    )
    def test_dag_mismatch(self, source_label, target_label, dag_id):
        # note that we don't have to test update() calls because we have it disabled
        # to force edges to only be created or updated (when key fields are involved)
        source = Node.objects.get(name=source_label)
        target = Node.objects.get(name=target_label)
        dag = DAG.objects.get(team=source.team, name=dag_id)
        with self.assertRaises(DAGMismatchError):
            Edge.objects.create(team=source.team, dag=dag, source=source, target=target)
