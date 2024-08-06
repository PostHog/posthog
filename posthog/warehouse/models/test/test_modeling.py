from django.core.exceptions import ValidationError

from posthog.test.base import BaseTest
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.modeling import DataWarehouseModelPath


class TestModelPath(BaseTest):
    def test_create_from_posthog_root_nodes_query(self):
        """Test creation of a model path from a query that reads from PostHog root tables."""
        query = """\
          select
            events.event,
            persons.properties
          from events
          left join persons on events.person_id = persons.id
          where events.event = 'login' and person.pdi != 'some_distinct_id'
        """
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query_instance(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 2)
        self.assertIn(["events", saved_query.id.hex], paths)
        self.assertIn(["persons", saved_query.id.hex], paths)

    def test_create_from_existing_path(self):
        """Test creation of a model path from a query that reads from another query."""
        parent_query = """\
          select
            events.event,
            persons.properties
          from events
          left join persons on events.person_id = persons.id
          where events.event = 'login' and person.pdi != 'some_distinct_id'
        """
        parent_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": parent_query},
        )
        child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_child",
            query={"query": "select * from my_model as my_other_model"},
        )

        parent_model_paths = DataWarehouseModelPath.objects.create_from_saved_query_instance(parent_saved_query)
        child_model_paths = DataWarehouseModelPath.objects.create_from_saved_query_instance(child_saved_query)

        parent_paths = [model_path.path for model_path in parent_model_paths]
        child_paths = [model_path.path for model_path in child_model_paths]

        self.assertEqual(len(parent_paths), 2)
        self.assertIn(["events", parent_saved_query.id.hex], parent_paths)
        self.assertIn(["persons", parent_saved_query.id.hex], parent_paths)

        self.assertEqual(len(child_paths), 2)
        self.assertIn(["events", parent_saved_query.id.hex, child_saved_query.id.hex], child_paths)
        self.assertIn(["persons", parent_saved_query.id.hex, child_saved_query.id.hex], child_paths)

    def test_validate_table_or_saved_query_is_set(self):
        """Test validation properly checks a path must have a query or a table."""
        model_path = DataWarehouseModelPath.objects.create(
            path=["abc", "abc"], team=self.team, table=None, saved_query=None
        )

        self.assertRaises(ValidationError, model_path.clean)

    def test_get_longest_common_ancestor_path(self):
        """Test resolving the longest common ancestor of two simple queries."""
        query_1 = """\
          select
            events.event
          from events
          where events.event = 'login'
        """
        query_2 = """\
          select
            events.person_id as person_id
          from events
          where events.event = 'logout'
        """

        saved_query_1 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model1",
            query={"query": query_1},
        )
        saved_query_2 = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model2",
            query={"query": query_2},
        )
        DataWarehouseModelPath.objects.create_from_saved_query_instance(saved_query_1)
        DataWarehouseModelPath.objects.create_from_saved_query_instance(saved_query_2)

        lca = DataWarehouseModelPath.objects.get_longest_common_ancestor_path([saved_query_1, saved_query_2])
        self.assertEqual(lca, "events")

    def test_get_dag(self):
        """Test the generation of a DAG with a couple simple models."""
        parent_query = """\
          select
            events.event,
            persons.properties
          from events
          left join persons on events.person_id = persons.id
          where events.event = 'login' and person.pdi != 'some_distinct_id'
        """
        parent_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": parent_query},
        )
        child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_child",
            query={"query": "select * from my_model as my_other_model"},
        )

        DataWarehouseModelPath.objects.create_from_saved_query_instance(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query_instance(child_saved_query)

        dag = DataWarehouseModelPath.objects.get_dag(team=self.team)

        self.assertIn((parent_saved_query.id.hex, child_saved_query.id.hex), dag.edges)
        self.assertIn(("events", parent_saved_query.id.hex), dag.edges)
        self.assertIn(("persons", parent_saved_query.id.hex), dag.edges)
        self.assertEqual(len(dag.edges), 3)

        self.assertIn((child_saved_query.id.hex, "SavedQuery"), dag.nodes)
        self.assertIn((parent_saved_query.id.hex, "SavedQuery"), dag.nodes)
        self.assertIn(("events", "PostHog"), dag.nodes)
        self.assertIn(("persons", "PostHog"), dag.nodes)
        self.assertEqual(len(dag.nodes), 4)
