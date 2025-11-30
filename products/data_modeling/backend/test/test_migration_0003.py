from typing import Any

import pytest
from freezegun import freeze_time
from posthog.test.base import NonAtomicTestMigrations

# maps case name to an args tuple (source_label, target_lable, should_raise)
TEST_CASES = {
    # low index to high index is always fine
    "linked_list_1": ("0", "2499", False),
    "linked_list_2": ("0", "50", False),
    "linked_list_3": ("0", "1", False),
    # self cycle case
    "linked_list_4": ("0", "0", True),
    # high index to low always causes a cycle
    "linked_list_5": ("1", "0", True),
    "linked_list_6": ("50", "0", True),
    "linked_list_7": ("2499", "0", True),
    # root to any grandchild is always fine
    "balanced_tree_1": ("root", "child_0_child_0", False),
    "balanced_tree_2": ("root", "child_25_child_0", False),
    "balanced_tree_3": ("root", "child_49_child_0", False),
    # child to any grandchild is always fine
    "balanced_tree_4": ("child_0", "child_1_child_0", False),
    "balanced_tree_5": ("child_0", "child_25_child_0", False),
    "balanced_tree_6": ("child_0", "child_49_child_0", False),
    # self cycle case
    "balanced_tree_7": ("root", "root", True),
    # child to root always causes a cycle
    "balanced_tree_8": ("child_0", "root", True),
    "balanced_tree_9": ("child_25", "root", True),
    "balanced_tree_10": ("child_49", "root", True),
    # grandchild to root always causes a cycle
    "balanced_tree_11": ("child_0_child_0", "root", True),
    "balanced_tree_12": ("child_25_child_0", "root", True),
    "balanced_tree_13": ("child_49_child_0", "root", True),
    # grandchild to any child not its parent is always fine (i.e. root -> 0 -> 0_0 -> 1 + root -> 1 = no cycle)
    "balanced_tree_14": ("child_1_child_0", "child_0", False),
    "balanced_tree_15": ("child_25_child_0", "child_0", False),
    "balanced_tree_16": ("child_49_child_0", "child_0", False),
    # any grandchild to its parent always causes a cycle
    "balanced_tree_17": ("child_0_child_0", "child_0", True),
    "balanced_tree_18": ("child_0_child_25", "child_0", True),
    "balanced_tree_19": ("child_0_child_49", "child_0", True),
    # any child to any other child is always fine
    "balanced_tree_20": ("child_0", "child_1", False),
    "balanced_tree_21": ("child_0", "child_25", False),
    "balanced_tree_22": ("child_0", "child_49", False),
    # any grandchild to any other grandchild is always fine
    "balanced_tree_23": ("child_0_child_0", "child_1_child_1", False),
    "balanced_tree_24": ("child_0_child_0", "child_25_child_25", False),
    "balanced_tree_25": ("child_0_child_0", "child_49_child_49", False),
}

LINKED_LIST_DAG_ID = "linked_list"
BALANCED_TREE_DAG_ID = "balanced_tree"


def _basic_saved_query_with_label(label: str):
    return f"""SELECT '{label}'"""


class CycleDetectionMigration(NonAtomicTestMigrations):
    migrate_from = "0002_edge"
    migrate_to = "0003_cycle_detection"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        DataWarehouseSavedQuery = apps.get_model("data_warehouse", "DataWarehouseSavedQuery")
        Node = apps.get_model("data_modeling", "Node")
        Edge = apps.get_model("data_modeling", "Edge")

        self.organization = Organization.objects.create(name="o1")
        self.project = Project.objects.create(organization=self.organization, name="p1", id=1000001)
        self.team = Team.objects.create(organization=self.organization, name="t1", project=self.project)
        self.team_id = self.team.id  # type: ignore

        with freeze_time("2025-01-01T12:00:00.000Z"):
            # generates a linked list of 2500 nodes
            ll_queries = DataWarehouseSavedQuery.objects.bulk_create(
                [
                    DataWarehouseSavedQuery(
                        name=f"ll_{i}",
                        team_id=self.team_id,
                        query=_basic_saved_query_with_label(str(i)),
                    )
                    for i in range(2500)
                ]
            )
            ll_nodes = Node.objects.bulk_create(
                [Node(team_id=self.team_id, dag_id=LINKED_LIST_DAG_ID, saved_query_id=query.id) for query in ll_queries]
            )
            Edge.objects.bulk_create(
                [
                    Edge(
                        team_id=self.team_id,
                        dag_id=LINKED_LIST_DAG_ID,
                        source_id=ll_nodes[i].id,
                        target_id=ll_nodes[i + 1].id,
                    )
                    for i in range(len(ll_nodes) - 1)
                ]
            )

            # generates a two tier tree: 1 root with 50 children and 2500 grandchilden (2551 nodes)
            bt_queries = DataWarehouseSavedQuery.objects.bulk_create(
                [
                    DataWarehouseSavedQuery(
                        name="bt_root",
                        team_id=self.team_id,
                        query=_basic_saved_query_with_label("root"),
                    )
                ]
                + [
                    DataWarehouseSavedQuery(
                        name=f"bt_child_{i}",
                        team_id=self.team_id,
                        query=_basic_saved_query_with_label(f"child_{i}"),
                    )
                    for i in range(50)
                ]
                + [
                    DataWarehouseSavedQuery(
                        name=f"bt_child_{i}_child_{j}",
                        team_id=self.team_id,
                        query=_basic_saved_query_with_label(f"child_{i}_child_{j}"),
                    )
                    for i in range(50)
                    for j in range(50)
                ]
            )
            bt_nodes = Node.objects.bulk_create(
                [
                    Node(team_id=self.team_id, dag_id=BALANCED_TREE_DAG_ID, saved_query_id=query.id)
                    for query in bt_queries
                ]
            )
            # 0 = root, 1-50 = children, 51+ = grandchildren
            root = bt_nodes[0]
            children = bt_nodes[1:51]
            edges = []
            for i, child in enumerate(children):
                edges.append(
                    Edge(team_id=self.team_id, dag_id=BALANCED_TREE_DAG_ID, source_id=root.id, target_id=child.id)
                )
                for j in range(50):
                    grandchild = bt_nodes[51 + i * 50 + j]
                    edges.append(
                        Edge(
                            team_id=self.team_id,
                            dag_id=BALANCED_TREE_DAG_ID,
                            source_id=child.id,
                            target_id=grandchild.id,
                        )
                    )
            Edge.objects.bulk_create(edges)

    def test_migration(self):
        Node = self.apps.get_model("data_modeling", "Node")  # type: ignore
        Edge = self.apps.get_model("data_modeling", "Edge")  # type: ignore
        for name, (source_label, target_label, should_raise) in TEST_CASES.items():
            label_prefix = "ll"
            dag_id = LINKED_LIST_DAG_ID
            if name.startswith(BALANCED_TREE_DAG_ID):
                label_prefix = "bt"
                dag_id = BALANCED_TREE_DAG_ID
            source = Node.objects.get(saved_query__name=f"{label_prefix}_{source_label}")
            target = Node.objects.get(saved_query__name=f"{label_prefix}_{target_label}")
            if should_raise:
                with pytest.raises(Exception):
                    Edge.objects.create(team=source.team, dag_id=dag_id, source=source, target=target)
            else:
                edge = Edge.objects.create(team=source.team, dag_id=dag_id, source=source, target=target)
                # clean up the edge so there are no unexpected conflicts in downstream tests
                edge.delete()

    def tearDown(self):
        self.team.delete()
        super().tearDown()
