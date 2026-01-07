from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_modeling.backend.models import CycleDetectionError, Edge, Node
from products.data_warehouse.backend.models import DataWarehouseSavedQuery
import pytest

LINKED_LIST_DAG_ID = "linked_list"
BALANCED_TREE_DAG_ID = "balanced_tree"


def _basic_saved_query_with_label(label: str):
    return f"""SELECT '{label}'"""


class LinkedListCycleDetectionTest(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with freeze_time("2025-01-01T12:00:00.000Z"):
            ll_queries = [
                DataWarehouseSavedQuery.objects.create(
                    name=f"ll_{i}",
                    team=cls.team,
                    query=_basic_saved_query_with_label(str(i)),
                )
                for i in range(25)
            ]
            ll_nodes = [
                Node.objects.create(team=cls.team, dag_id=LINKED_LIST_DAG_ID, saved_query=query, name=f"ll_{i}")
                for i, query in enumerate(ll_queries)
            ]
            for i in range(len(ll_nodes) - 1):
                Edge.objects.create(
                    team=cls.team,
                    dag_id=LINKED_LIST_DAG_ID,
                    source=ll_nodes[i],
                    target=ll_nodes[i + 1],
                )

    @parameterized.expand(
        [
            # low index to high index is always fine
            ("0", "24", False),
            ("0", "5", False),
            ("0", "2", False),  # note 0, 1 would be a duplicate edge and would fail
            # self cycle case
            ("0", "0", True),
            # high index to low always causes a cycle
            ("1", "0", True),
            ("5", "0", True),
            ("24", "0", True),
        ],
    )
    def test_linked_list_dag(self, source_label, target_label, should_raise):
        source = Node.objects.get(saved_query__name=f"ll_{source_label}")
        target = Node.objects.get(saved_query__name=f"ll_{target_label}")
        if should_raise:
            with pytest.raises(Exception):
                Edge.objects.create(team=source.team, dag_id=LINKED_LIST_DAG_ID, source=source, target=target)
        else:
            edge = Edge.objects.create(team=source.team, dag_id=LINKED_LIST_DAG_ID, source=source, target=target)
            edge.delete()


class TreeCycleDetectionTest(BaseTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with freeze_time("2025-01-01T12:00:00.000Z"):
            bt_root = [
                DataWarehouseSavedQuery.objects.create(
                    name="bt_root",
                    team=cls.team,
                    query=_basic_saved_query_with_label("root"),
                )
            ]
            bt_children = [
                DataWarehouseSavedQuery.objects.create(
                    name=f"bt_child_{i}",
                    team=cls.team,
                    query=_basic_saved_query_with_label(f"child_{i}"),
                )
                for i in range(5)
            ]
            bt_grandchildren = [
                DataWarehouseSavedQuery.objects.create(
                    name=f"bt_child_{i}_child_{j}",
                    team=cls.team,
                    query=_basic_saved_query_with_label(f"child_{i}_child_{j}"),
                )
                for i in range(5)
                for j in range(5)
            ]
            bt_nodes = [
                Node.objects.create(team=cls.team, dag_id=BALANCED_TREE_DAG_ID, saved_query=query, name=query.name)
                for query in bt_root + bt_children + bt_grandchildren
            ]
            root = bt_nodes[0]
            children = bt_nodes[1:6]
            for i, child in enumerate(children):
                Edge.objects.create(team=cls.team, dag_id=BALANCED_TREE_DAG_ID, source=root, target=child)
                for j in range(5):
                    grandchild = bt_nodes[6 + i * 5 + j]
                    Edge.objects.create(
                        team=cls.team,
                        dag_id=BALANCED_TREE_DAG_ID,
                        source=child,
                        target=grandchild,
                    )

    @parameterized.expand(
        [
            # root to any grandchild is always fine
            ("root", "child_0_child_0", False),
            ("root", "child_2_child_0", False),
            ("root", "child_4_child_0", False),
            # child to any grandchild is always fine
            ("child_0", "child_1_child_0", False),
            ("child_0", "child_2_child_0", False),
            ("child_0", "child_4_child_0", False),
            # self cycle case
            ("root", "root", True),
            # child to root always causes a cycle
            ("child_0", "root", True),
            ("child_2", "root", True),
            ("child_4", "root", True),
            # grandchild to root always causes a cycle
            ("child_0_child_0", "root", True),
            ("child_2_child_0", "root", True),
            ("child_4_child_0", "root", True),
            # grandchild to any child not its parent is always fine (i.e. root -> 0 -> 0_0 -> 1 + root -> 1 = no cycle)
            ("child_1_child_0", "child_0", False),
            ("child_2_child_0", "child_0", False),
            ("child_4_child_0", "child_0", False),
            # any grandchild to its parent always causes a cycle
            ("child_0_child_0", "child_0", True),
            ("child_0_child_2", "child_0", True),
            ("child_0_child_4", "child_0", True),
            # any child to any other child is always fine
            ("child_0", "child_1", False),
            ("child_0", "child_2", False),
            ("child_0", "child_4", False),
            # any grandchild to any other grandchild is always fine
            ("child_0_child_0", "child_1_child_1", False),
            ("child_0_child_0", "child_2_child_2", False),
            ("child_0_child_0", "child_4_child_4", False),
        ],
    )
    def test_tree_like_dag(self, source_label, target_label, should_raise):
        source = Node.objects.get(saved_query__name=f"bt_{source_label}")
        target = Node.objects.get(saved_query__name=f"bt_{target_label}")
        if should_raise:
            with pytest.raises(CycleDetectionError):
                Edge.objects.create(team=source.team, dag_id=BALANCED_TREE_DAG_ID, source=source, target=target)
        else:
            edge = Edge.objects.create(team=source.team, dag_id=BALANCED_TREE_DAG_ID, source=source, target=target)
            edge.delete()

    def test_disallowed_object_functions(self):
        test_team = self.team
        test_node = Node.objects.get(name="bt_root")
        bt_edges = Edge.objects.filter(dag_id=BALANCED_TREE_DAG_ID)
        disallowed = ("dag_id", "source", "source_id", "target", "target_id", "team", "team_id")
        for key in disallowed:
            # test update disallowed for each key
            with pytest.raises(NotImplementedError):
                if key.endswith("id"):
                    bt_edges.update(**{key: "test"})
                elif key == "source":
                    bt_edges.update(source=test_node)
                elif key == "target":
                    bt_edges.update(target=test_node)
                elif key == "team":
                    bt_edges.update(team=test_team)
            # test bulk_update disallowed for each key
            mock_edges = [Edge(source=test_node, target=test_node, team=test_team, dag_id="test") for _ in range(3)]
            for edge in mock_edges:
                if key.endswith("id"):
                    setattr(edge, key, "test")
                elif key in ("source", "target"):
                    setattr(edge, key, test_node)
                elif key == "team":
                    setattr(edge, key, test_team)
            with pytest.raises(NotImplementedError):
                Edge.objects.bulk_update(mock_edges, [key])
        # test bulk_create disallowed
        with pytest.raises(NotImplementedError):
            Edge.objects.bulk_create(bt_edges)
