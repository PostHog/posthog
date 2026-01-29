import pytest
from posthog.test.base import BaseTest

from posthog.models import DataWarehouseTable

from products.data_warehouse.backend.models import ExternalDataSchema, ExternalDataSource, ExternalDataSourceType
from products.data_warehouse.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.modeling import (
    DataWarehouseModelPath,
    ModelPathCycleError,
    NodeType,
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
        # CTE with UNION ALL at top level - the CTE should not be treated as a parent
        (
            """
            WITH cte AS (SELECT * FROM events)
            SELECT * FROM cte
            UNION ALL
            SELECT * FROM cte
            """,
            {"events"},
        ),
    ],
)
def test_get_parents_from_model_query(query: str, parents: set[str]):
    """Test parents are correctly parsed from sample queries."""
    assert parents == get_parents_from_model_query(query)


class TestModelPath(BaseTest):
    def test_create_from_static_query(self):
        """Test creation of a model path from a query that returns a static set of rows."""
        query = "SELECT 1 AS a, 2 AS b, NOW() AS c"
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)

        paths = [model_path.path for model_path in model_paths]
        self.assertEqual(len(paths), 1)
        self.assertIn([saved_query.id.hex], paths)

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

    def test_update_child_when_parent_has_multiple_paths_does_not_crash(self):
        """Test updating a child model when its parent has multiple paths doesn't crash.

        This tests the fix for CardinalityViolation that occurred when a parent
        had multiple paths (e.g., from selecting from multiple root tables).
        The cross join in UPDATE_PATHS_QUERY would produce duplicate IDs,
        which PostgreSQL rejected. Using DISTINCT ON (id) fixes this.

        The UPDATE_PATHS_QUERY only updates descendant paths (where the child
        has something after it), so we need a grandchild to trigger the cross join.
        """
        parent_query = """\
          select
            events.event,
            persons.properties
          from events
          left join persons on events.person_id = persons.id
        """
        parent_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="parent",
            query={"query": parent_query},
        )
        child_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="child",
            query={"query": "select * from parent"},
        )
        grandchild_saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="grandchild",
            query={"query": "select * from child"},
        )

        DataWarehouseModelPath.objects.create_from_saved_query(parent_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(child_saved_query)
        DataWarehouseModelPath.objects.create_from_saved_query(grandchild_saved_query)

        parent_paths = list(
            DataWarehouseModelPath.objects.filter(saved_query=parent_saved_query).values_list("path", flat=True)
        )
        self.assertEqual(len(parent_paths), 2)
        child_saved_query.query = {"query": "select event, properties from parent where event = 'login'"}
        child_saved_query.save()

        # this would raise ProgrammingError with "CardinalityViolation"" before we were using DISTINCT ON (id)
        DataWarehouseModelPath.objects.update_from_saved_query(child_saved_query)
        grandchild_paths = list(
            DataWarehouseModelPath.objects.filter(saved_query=grandchild_saved_query).values_list("path", flat=True)
        )
        self.assertGreaterEqual(len(grandchild_paths), 1)
        # verify the lineage is still correct
        self.assertEqual(grandchild_paths[0][-1], grandchild_saved_query.id.hex)
        self.assertEqual(grandchild_paths[0][-2], child_saved_query.id.hex)
        self.assertEqual(grandchild_paths[0][-3], parent_saved_query.id.hex)

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

        with pytest.raises(ModelPathCycleError):
            DataWarehouseModelPath.objects.update_from_saved_query(child_saved_query)
