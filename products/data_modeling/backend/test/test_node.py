import uuid

import pytest
from posthog.test.base import BaseTest

from django.db import IntegrityError

from parameterized import parameterized

from products.data_modeling.backend.models import DAG
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_modeling.backend.models.node import Node, NodeType


@pytest.mark.django_db
class TestNodeNameSync(BaseTest):
    def test_node_name_syncs_from_saved_query_on_save(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="original_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        dag = DAG.objects.create(team=self.team, name="test")

        node = Node.objects.create(
            team=self.team,
            dag=dag,
            name="ignored_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        self.assertEqual(node.name, "original_name")

    def test_node_name_cannot_be_overridden_when_saved_query_exists(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="saved_query_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        dag = DAG.objects.create(team=self.team, name="test")

        node = Node.objects.create(
            team=self.team,
            dag=dag,
            name="saved_query_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        node.name = "attempted_override"
        node.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "saved_query_name")

    def test_node_name_updates_when_saved_query_name_changes(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="original_name",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        dag = DAG.objects.create(team=self.team, name="test")

        node = Node.objects.create(
            team=self.team,
            dag=dag,
            name="original_name",
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        saved_query.name = "updated_name"
        saved_query.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "updated_name")

    def test_table_node_name_is_not_affected_by_sync(self):
        dag = DAG.objects.create(team=self.team, name="test")
        node = Node.objects.create(
            team=self.team,
            dag=dag,
            name="events",
            saved_query=None,
            type=NodeType.TABLE,
        )

        self.assertEqual(node.name, "events")

        node.name = "custom_table_name"
        node.save()

        node.refresh_from_db()
        self.assertEqual(node.name, "custom_table_name")

    def test_node_without_saved_query_requires_name(self):
        dag = DAG.objects.create(team=self.team, name="test")
        with self.assertRaises(ValueError) as context:
            Node.objects.create(
                team=self.team,
                dag=dag,
                name="",
                saved_query=None,
                type=NodeType.TABLE,
            )

        self.assertEqual(str(context.exception), "Node without a saved_query must have a name")

    def test_multiple_nodes_can_share_saved_query_across_different_dags(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="shared_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        dag_one = DAG.objects.create(team=self.team, name="dag_one")
        dag_two = DAG.objects.create(team=self.team, name="dag_two")

        node1 = Node.objects.create(
            team=self.team,
            dag=dag_one,
            saved_query=saved_query,
            type=NodeType.VIEW,
        )
        node2 = Node.objects.create(
            team=self.team,
            dag=dag_two,
            saved_query=saved_query,
            type=NodeType.VIEW,
        )

        self.assertEqual(node1.saved_query_id, node2.saved_query_id)
        self.assertEqual(node1.name, "shared_view")
        self.assertEqual(node2.name, "shared_view")

        saved_query.name = "renamed_view"
        saved_query.save()

        node1.refresh_from_db()
        node2.refresh_from_db()
        self.assertEqual(node1.name, "renamed_view")
        self.assertEqual(node2.name, "renamed_view")

    def test_multiple_nodes_cannot_share_saved_query_in_same_dag(self):
        saved_query = DataWarehouseSavedQuery.objects.create(
            name="shared_view",
            team=self.team,
            query={"query": "SELECT 1", "kind": "HogQLQuery"},
        )
        dag = DAG.objects.create(team=self.team, name="dag_one")
        Node.objects.create(
            team=self.team,
            dag=dag,
            saved_query=saved_query,
            type=NodeType.VIEW,
        )
        with pytest.raises(IntegrityError):
            Node.objects.create(
                team=self.team,
                dag=dag,
                saved_query=saved_query,
                type=NodeType.VIEW,
            )


@pytest.mark.django_db
class TestMetricNode(BaseTest):
    def setUp(self):
        super().setUp()
        self.dag = DAG.objects.create(team=self.team, name="test")

    def test_metric_node_carries_its_metric_id(self):
        metric_id = uuid.uuid4()

        node = Node.objects.create(
            team=self.team,
            dag=self.dag,
            name="weekly_active_accounts",
            type=NodeType.METRIC,
            metric_id=metric_id,
        )

        node.refresh_from_db()
        self.assertEqual(node.metric_id, metric_id)

    @parameterized.expand(
        [
            ("metric_without_metric_id", NodeType.METRIC, False, False),
            ("metric_with_saved_query", NodeType.METRIC, True, False),
            ("metric_with_saved_query_and_metric_id", NodeType.METRIC, True, True),
            ("table_with_metric_id", NodeType.TABLE, False, True),
            ("view_with_metric_id", NodeType.VIEW, True, True),
            ("view_without_saved_query", NodeType.VIEW, False, False),
        ]
    )
    def test_backing_reference_must_match_type(self, _name, node_type, with_saved_query, with_metric_id):
        saved_query = (
            DataWarehouseSavedQuery.objects.create(
                name="a_view",
                team=self.team,
                query={"query": "SELECT 1", "kind": "HogQLQuery"},
            )
            if with_saved_query
            else None
        )

        with pytest.raises(IntegrityError):
            Node.objects.create(
                team=self.team,
                dag=self.dag,
                name="a_name",
                type=node_type,
                saved_query=saved_query,
                metric_id=uuid.uuid4() if with_metric_id else None,
            )

    def test_one_node_per_metric_in_a_dag(self):
        metric_id = uuid.uuid4()
        Node.objects.create(team=self.team, dag=self.dag, name="revenue", type=NodeType.METRIC, metric_id=metric_id)

        with pytest.raises(IntegrityError):
            Node.objects.create(
                team=self.team, dag=self.dag, name="revenue_renamed", type=NodeType.METRIC, metric_id=metric_id
            )

    def test_a_metric_may_share_a_name_with_a_table(self):
        Node.objects.create(team=self.team, dag=self.dag, name="events", type=NodeType.TABLE)

        metric = Node.objects.create(
            team=self.team, dag=self.dag, name="events", type=NodeType.METRIC, metric_id=uuid.uuid4()
        )

        self.assertEqual(metric.name, "events")
