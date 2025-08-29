import pytest
from posthog.test.base import BaseTest

from django.db.utils import ProgrammingError

from posthog.models import DataWarehouseTable
from posthog.warehouse.models import ExternalDataSchema, ExternalDataSource, ExternalDataSourceType
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.modeling import (
    DataWarehouseModelPath,
    NodeType,
    UnknownParentError,
    get_parents_from_model_query,
)


@pytest.mark.parametrize(
    "query,parents",
    [
        ("select * from events, persons", {"events", "persons"}),
        ("select * from some_random_view", {"some_random_view"}),
        (
            "with cte as (select * from events), cte2 as (select * from cte), cte3 as (select 1) select * from cte2",
            {"events"},
        ),
        ("select 1", set()),
        (
            """
            select *
            from (
              select 1 as id, *
              from events
              inner join (
                select * from
                (
                  select number
                  from numbers(10)
                )
              ) num on events.id = num.number
            )
            """,
            {"events", "numbers"},
        ),
        ("select * from (select * from (select * from (select * from events)))", {"events"}),
        (
            """
            select *
            from (
              select number from numbers(5)
              union all
              select event from events
            )
            """,
            {"numbers", "events"},
        ),
    ],
)
def test_get_parents_from_model_query(query: str, parents: set[str]):
    """Test parents are correctly parsed from sample queries."""
    assert parents == get_parents_from_model_query(query)


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

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 2)
        self.assertIn(["events", saved_query.id.hex], paths)
        self.assertIn(["persons", saved_query.id.hex], paths)

    def test_create_from_warehouse_table_old_notation_nodes_query(self):
        """Test creation of a model path from a query that reads from a managed source using old notation."""

        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.STRIPE)
        table = DataWarehouseTable.objects.create(team=self.team, name="stripe_invoice", external_data_source=source)
        ExternalDataSchema.objects.create(team=self.team, name="Invoice", source=source, table=table)

        query = """\
          select *
          from stripe_invoice
        """
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 1)
        self.assertIn([table.id.hex, saved_query.id.hex], paths)

    def test_create_from_warehouse_table_new_notation_nodes_query(self):
        """Test creation of a model path from a query that reads from a managed source using new notation."""

        source = ExternalDataSource.objects.create(team=self.team, source_type=ExternalDataSourceType.STRIPE)
        table = DataWarehouseTable.objects.create(team=self.team, name="stripe_invoice", external_data_source=source)
        ExternalDataSchema.objects.create(team=self.team, name="Invoice", source=source, table=table)

        query = """\
          select *
          from stripe.invoice
        """
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 1)
        self.assertIn([table.id.hex, saved_query.id.hex], paths)

    def test_create_from_table_functions_root_nodes_query(self):
        query = "select * from numbers(10)"
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 1)
        self.assertIn(["numbers", saved_query.id.hex], paths)

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

        parent_model_paths = DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        child_model_paths = DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)

        parent_paths = [model_path.path for model_path in parent_model_paths]
        child_paths = [model_path.path for model_path in child_model_paths]

        self.assertEqual(len(parent_paths), 2)
        self.assertIn(["events", parent_saved_query.id.hex], parent_paths)
        self.assertIn(["persons", parent_saved_query.id.hex], parent_paths)

        self.assertEqual(len(child_paths), 2)
        self.assertIn(["events", parent_saved_query.id.hex, child_saved_query.id.hex], child_paths)
        self.assertIn(["persons", parent_saved_query.id.hex, child_saved_query.id.hex], child_paths)

    def test_update_path_from_saved_query(self):
        """Test update of a model path from a query that reads from another query."""
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
        grand_child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_grand_child",
            query={"query": "select * from my_model_child"},
        )

        DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(grand_child_saved_query)

        child_saved_query.query = {"query": "select * from events as my_other_model"}
        child_saved_query.save()
        DataWarehouseModelPath.objects.update_from_saved_query(child_saved_query)

        child_refreshed_model_paths = DataWarehouseModelPath.objects.filter(
            team=self.team, saved_query=child_saved_query
        ).all()
        child_paths = [model_path.path for model_path in child_refreshed_model_paths]
        grand_child_refreshed_model_paths = DataWarehouseModelPath.objects.filter(
            team=self.team, saved_query=grand_child_saved_query
        ).all()
        grand_child_paths = [model_path.path for model_path in grand_child_refreshed_model_paths]

        self.assertEqual(len(child_paths), 1)
        self.assertIn(["events", child_saved_query.id.hex], child_paths)
        self.assertEqual(len(grand_child_paths), 1)
        self.assertIn(["events", child_saved_query.id.hex, grand_child_saved_query.id.hex], grand_child_paths)

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
        DataWarehouseModelPath.objects.create_from_saved_query(saved_query_1)
        DataWarehouseModelPath.objects.create_from_saved_query(saved_query_2)

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

        DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)

        dag = DataWarehouseModelPath.objects.get_dag(team=self.team)

        self.assertIn((parent_saved_query.id.hex, child_saved_query.id.hex), dag.edges)
        self.assertIn(("events", parent_saved_query.id.hex), dag.edges)
        self.assertIn(("persons", parent_saved_query.id.hex), dag.edges)
        self.assertEqual(len(dag.edges), 3)

        self.assertIn((child_saved_query.id.hex, NodeType.SAVED_QUERY), dag.nodes)
        self.assertIn((parent_saved_query.id.hex, NodeType.SAVED_QUERY), dag.nodes)
        self.assertIn(("events", NodeType.POSTHOG), dag.nodes)
        self.assertIn(("persons", NodeType.POSTHOG), dag.nodes)
        self.assertEqual(len(dag.nodes), 4)

    def test_creating_cycles_raises_exception(self):
        """Test cycles cannot be created just by creating queries that select from each other."""
        cycling_child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_other_model_child",
            query={"query": "select * from my_model_grand_child"},
        )

        grand_child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_grand_child",
            query={"query": "select * from my_other_model_child"},
        )

        with pytest.raises(UnknownParentError):
            DataWarehouseModelPath.objects.create_from_saved_query(grand_child_saved_query)
            DataWarehouseModelPath.objects.create_from_saved_query(cycling_child_saved_query)

    def test_creating_cycles_via_updates_raises_exception(self):
        """Test cycles cannot be created just by updating queries that select from each other."""
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
            query={"query": "select * from my_model"},
        )
        grand_child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model_grand_child",
            query={"query": "select * from my_model_child"},
        )

        DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(grand_child_saved_query)

        child_saved_query.query = {"query": "select * from my_model union all select * from my_model_grand_child"}
        child_saved_query.save()

        with pytest.raises(ProgrammingError):
            DataWarehouseModelPath.objects.update_from_saved_query(child_saved_query)
