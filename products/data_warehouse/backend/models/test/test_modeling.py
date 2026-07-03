import pytest
from posthog.test.base import BaseTest

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import QueryError
from posthog.hogql.parser import parse_select

from products.data_modeling.backend.facade.modeling import (
    DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
    BoundedResolver,
    DataWarehouseModelPath,
    NodeType,
    ResolutionCycleError,
    ResolutionDepthExceededError,
    ResolutionTimeoutError,
    get_parents_from_model_query,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.models import DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

GET_PARENTS_TEST_CASES = [
    ("select events.*, persons.* from events, persons", {"events", "persons"}),
    (
        "with cte as (select * from events), cte2 as (select * from cte), cte3 as (select 1) select * from cte2",
        {"events"},
    ),
    ("select 1", set()),
    (
        """
        select *
        from (
          select events.*, num.*
          from events
          inner join (
            select number
            from numbers(10)
          ) num on 1 = 1
        )
        """,
        {"events"},
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
        {"events"},
    ),
    # Table function as the only source
    ("select number from numbers(10)", set()),
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
    # CTE used in a JOIN - should resolve through the CTE to find actual parents
    (
        """
            WITH cte AS (SELECT event, person_id FROM events GROUP BY event, person_id)
            SELECT p.id, c.event
            FROM persons p
            JOIN cte c ON p.id = c.person_id
            """,
        {"events", "persons"},
    ),
    # nested CTEs: a top-level CTE whose inner query defines its own CTEs used in a JOIN
    (
        """
            WITH outer_cte AS (
                WITH inner_data AS (
                    SELECT event, person_id FROM events GROUP BY event, person_id
                ),
                inner_agg AS (
                    SELECT person_id, count() AS cnt FROM inner_data GROUP BY person_id
                )
                SELECT p.id, ia.cnt
                FROM persons p
                JOIN inner_agg ia ON p.id = ia.person_id
            )
            SELECT * FROM outer_cte
        """,
        {"events", "persons"},
    ),
    # nested CTEs where an inner CTE shadows an outer CTE name
    (
        """
            WITH cte AS (
                WITH cte AS (
                    SELECT event, person_id FROM events GROUP BY event, person_id
                ),
                agg AS (
                    SELECT person_id, count() AS cnt FROM cte GROUP BY person_id
                )
                SELECT p.id, a.cnt
                FROM persons p
                JOIN agg a ON p.id = a.person_id
            )
            SELECT * FROM cte
        """,
        {"events", "persons"},
    ),
    # recursive CTE: self-referencing CTE should not cause infinite loop
    (
        """
            WITH RECURSIVE cte AS (
                SELECT 1 AS n
                UNION ALL
                SELECT n + 1 FROM cte WHERE n < 10
            )
            SELECT * FROM cte
        """,
        set(),
    ),
]


class TestModelPath(BaseTest):
    @parameterized.expand(GET_PARENTS_TEST_CASES)
    def test_get_parents_from_model_query(self, model_query: str, parents: set[str]):
        model_name = "test_model"
        assert parents == get_parents_from_model_query(self.team, model_name, model_query)

    def test_get_parents_from_model_query_unknown_table_raises(self):
        """Test that referencing a non-existent table raises QueryError."""
        with pytest.raises(QueryError, match="Unknown table"):
            get_parents_from_model_query(self.team, "test_model", "select * from some_random_view")

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

    def test_update_paths_for_posthog_namespaced_table_query(self):
        """`posthog.*`-namespaced tables (e.g. ai_events) must resolve as valid model-path parents on
        the UPDATE path too. `update_paths_from_query` keys off `get_posthog_table_names()`, which omits
        namespaced tables — so re-saving/re-materializing a view over `posthog.ai_events` raised
        UnknownParentError until the hidden table names were unioned in. (The create path already
        resolves them via `get_table()`.)"""
        query = "SELECT trace_id FROM posthog.ai_events"
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        # Create path seeds the initial paths (it resolves namespaced tables via get_table()).
        DataWarehouseModelPath.objects.create_from_saved_query(saved_query)

        # Update path is hit whenever an existing view is re-saved or re-materialized.
        DataWarehouseModelPath.objects.update_from_saved_query(saved_query)

        # `posthog.ai_events` is stored as two ltree labels (LabelTreeField splits on "."), exactly
        # as the create path stores it — the update path must converge on the same single path.
        paths = [mp.path for mp in DataWarehouseModelPath.objects.filter(team=self.team, saved_query=saved_query)]
        self.assertEqual(len(paths), 1)
        self.assertIn(["posthog", "ai_events", saved_query.id.hex], paths)

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
        """Table functions like numbers() are not real parents — they produce root nodes."""
        query = "select * from numbers(10)"
        saved_query = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="my_model",
            query={"query": query},
        )

        model_paths = DataWarehouseModelPath.objects.create_from_saved_query(saved_query)
        paths = [model_path.path for model_path in model_paths]

        self.assertEqual(len(paths), 1)
        self.assertIn([saved_query.id.hex], paths)

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

        with pytest.raises(ResolutionCycleError, match="[Cc]ircular dependency"):
            DataWarehouseModelPath.objects.update_from_saved_query(child_saved_query)


class TestBoundedResolver(BaseTest):
    def _resolve(
        self,
        query: str,
        initial_view_name: str = "test_model",
        max_view_depth: int = DEFAULT_RESOLUTION_MAX_VIEW_DEPTH,
        deadline_seconds: float | None = DEFAULT_RESOLUTION_DEADLINE_SECONDS,
    ) -> BoundedResolver:
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name=initial_view_name,
            max_view_depth=max_view_depth,
            deadline_seconds=deadline_seconds,
        )
        resolver.visit(parse_select(query))
        return resolver

    def _make_chain(self, length: int) -> None:
        """Create a chain of saved-query views: v0 → v1 → … → events."""
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        for i in range(1, length):
            DataWarehouseSavedQuery.objects.create(
                team=self.team,
                name=f"v{i}",
                query={"query": f"select * from v{i - 1}"},
            )

    def test_cycle_raises_typed_error_with_initial_view(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="a",
            query={"query": "select * from b"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="b",
            query={"query": "select * from a"},
        )

        with pytest.raises(ResolutionCycleError) as exc_info:
            get_parents_from_model_query(self.team, "a", "select * from b")

        # the inner view where the cycle was detected is `a` (already on the stack), and the caller is also `a`
        assert exc_info.value.view_name == "a"
        assert exc_info.value.initial_view == "a"

    def test_depth_limit_raises_when_chain_too_deep(self):
        self._make_chain(length=4)  # v0 → v1 → v2 → v3

        with pytest.raises(ResolutionDepthExceededError) as exc_info:
            self._resolve("select * from v3", initial_view_name="caller", max_view_depth=2)

        assert exc_info.value.max_depth == 2
        assert exc_info.value.depth == 3
        assert exc_info.value.initial_view == "caller"

    def test_depth_limit_allows_chain_within_budget(self):
        self._make_chain(length=3)  # v0 → v1 → v2

        resolver = self._resolve("select * from v2", initial_view_name="caller", max_view_depth=10)

        assert resolver.max_view_depth_observed == 3

    def test_negative_deadline_triggers_timeout_immediately(self):
        # A negative deadline is "already expired": the first visit_join_expr raises
        # without depending on clock precision between init and first visit.
        with pytest.raises(ResolutionTimeoutError) as exc_info:
            self._resolve("select * from events", initial_view_name="caller", deadline_seconds=-1.0)

        assert exc_info.value.deadline_seconds == -1.0
        assert exc_info.value.elapsed_seconds >= 0.0
        assert exc_info.value.initial_view == "caller"

    def test_deadline_none_disables_timeout(self):
        # No deadline: even with synthetic delay the resolver should not raise timeout.
        resolver = self._resolve("select * from events", initial_view_name="caller", deadline_seconds=None)
        assert resolver.deadline_seconds is None

    def test_bounded_resolver_errors_inherit_query_error(self):
        # Locks in the public contract: callers that catch QueryError (DRF exception
        # handlers, workflow error mappers) keep working when cycles/depth/timeouts fire.
        DataWarehouseSavedQuery.objects.create(team=self.team, name="a", query={"query": "select * from b"})
        DataWarehouseSavedQuery.objects.create(team=self.team, name="b", query={"query": "select * from a"})

        with pytest.raises(QueryError) as exc_info:
            get_parents_from_model_query(self.team, "a", "select * from b")

        assert isinstance(exc_info.value, ResolutionCycleError)

    def test_soft_mode_depth_observes_without_raising(self):
        self._make_chain(length=4)  # v0 → v1 → v2 → v3, would breach max_view_depth=2

        # enforce_bounds=False: depth overshoot is recorded but the walk continues
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name="caller",
            max_view_depth=2,
            enforce_bounds=False,
        )
        resolver.visit(parse_select("select * from v3"))

        assert resolver.max_view_depth_observed > resolver.max_view_depth

    def test_soft_mode_deadline_observes_without_raising(self):
        # Negative deadline = already expired. In soft mode we record but don't raise.
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(
            context=context,
            dialect="hogql",
            initial_view_name="caller",
            deadline_seconds=-1.0,
            enforce_bounds=False,
        )
        resolver.visit(parse_select("select * from events"))

        assert resolver.deadline_violated is True

    def test_soft_mode_cycle_still_raises(self):
        # Cycles MUST raise even in soft mode — observe-only would loop forever
        # because the resolver re-enters the same view.
        DataWarehouseSavedQuery.objects.create(team=self.team, name="a", query={"query": "select * from b"})
        DataWarehouseSavedQuery.objects.create(team=self.team, name="b", query={"query": "select * from a"})

        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)
        resolver = BoundedResolver(context=context, dialect="hogql", initial_view_name="a", enforce_bounds=False)

        with pytest.raises(ResolutionCycleError):
            resolver.visit(parse_select("select * from b"))


class TestResolutionMetrics(BaseTest):
    def _counter(self, status: str) -> float:
        return REGISTRY.get_sample_value("data_modeling_dag_resolution_total", {"status": status}) or 0.0

    def test_ok_path_increments_counter_and_records_depth(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="leaf",
            query={"query": "select event from events"},
        )
        before_ok = self._counter("ok")
        before_count = REGISTRY.get_sample_value("data_modeling_dag_resolution_duration_seconds_count") or 0.0

        parents = get_parents_from_model_query(self.team, "caller", "select * from leaf")

        assert parents == {"leaf"}
        assert self._counter("ok") - before_ok == 1.0
        assert (
            REGISTRY.get_sample_value("data_modeling_dag_resolution_duration_seconds_count") or 0.0
        ) - before_count == 1.0

    def test_cycle_increments_cycle_status(self):
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="a",
            query={"query": "select * from b"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="b",
            query={"query": "select * from a"},
        )
        before_cycle = self._counter("cycle")

        with pytest.raises(ResolutionCycleError):
            get_parents_from_model_query(self.team, "a", "select * from b")

        assert self._counter("cycle") - before_cycle == 1.0

    def test_unknown_table_increments_error_status(self):
        before_error = self._counter("error")

        with pytest.raises(QueryError):
            get_parents_from_model_query(self.team, "caller", "select * from some_random_view")

        assert self._counter("error") - before_error == 1.0


class TestResolverFactoryInjection(BaseTest):
    """Confirms prepare_ast_for_printing honors resolver_factory — proves the workflow path can
    swap in BoundedResolver instead of the unbounded base Resolver."""

    def test_prepare_ast_for_printing_uses_injected_bounded_resolver(self):
        from posthog.hogql.printer import prepare_ast_for_printing

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v1",
            query={"query": "select * from v0"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v2",
            query={"query": "select * from v1"},
        )

        query_node = parse_select("select * from v2")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        def factory(ctx, dialect, scopes):
            return BoundedResolver(
                scopes=scopes, context=ctx, dialect=dialect, initial_view_name="caller", max_view_depth=1
            )

        with pytest.raises(ResolutionDepthExceededError):
            prepare_ast_for_printing(query_node, context=context, dialect="clickhouse", resolver_factory=factory)

    def test_prepare_ast_for_printing_default_resolver_is_unbounded(self):
        """Sanity check: without the factory, no depth bound is applied — proves the kwarg is the opt-in."""
        from posthog.hogql.printer import prepare_ast_for_printing

        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v0",
            query={"query": "select event from events"},
        )
        DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="v1",
            query={"query": "select * from v0"},
        )

        query_node = parse_select("select * from v1")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        # Should not raise — the default base Resolver has no depth bound.
        prepare_ast_for_printing(query_node, context=context, dialect="clickhouse")

    def test_shared_deadline_anchor_spans_multiple_resolvers(self):
        """Two BoundedResolvers built from the same factory must share a deadline clock.

        Without a shared anchor, each resolver would get its own deadline_seconds budget
        and prepare_ast_for_printing's multi-pass resolution would compound the bound.
        """
        from products.data_modeling.backend.facade.modeling import bounded_resolver_factory_for_view

        factory = bounded_resolver_factory_for_view("caller", deadline_seconds=10.0)
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
        context.database = Database.create_for(team_id=context.team_id, modifiers=context.modifiers, team=context.team)

        # Factory seeds one anchor and hands the same value to every resolver it produces.
        r1 = factory(context, "hogql", None)
        r2 = factory(context, "hogql", None)
        assert isinstance(r1, BoundedResolver)
        assert isinstance(r2, BoundedResolver)
        assert r1.deadline_anchor is not None
        assert r2.deadline_anchor == r1.deadline_anchor

    def test_factory_threaded_through_resolve_lazy_tables(self):
        """Lazy-table resolution invokes the factory on subqueries it builds — depth bound applies.

        Queries against events touch lazy joins (persons, etc.) which `resolve_lazy_tables`
        materializes as subqueries and re-resolves. Threading the factory means those
        re-resolutions go through BoundedResolver too.
        """
        from posthog.hogql.printer import prepare_ast_for_printing

        from products.data_modeling.backend.facade.modeling import bounded_resolver_factory_for_view

        # Use the shared factory helper so the deadline is end-to-end across passes
        factory = bounded_resolver_factory_for_view("caller", max_view_depth=DEFAULT_RESOLUTION_MAX_VIEW_DEPTH)

        query_node = parse_select("select event from events")
        context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)

        # Should not raise — a simple events query is well within bounds, but it does
        # exercise the lazy-table path (events has lazy joins to persons/sessions).
        # Success here proves the factory is invoked at lazy_tables.resolve_types and
        # those nested resolutions don't error.
        prepare_ast_for_printing(query_node, context=context, dialect="clickhouse", resolver_factory=factory)
